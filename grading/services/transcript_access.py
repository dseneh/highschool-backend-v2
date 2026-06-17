"""Transcript download authorization, requests, and delivery."""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import Optional

from django.conf import settings as django_settings
from django.core.mail import EmailMessage
from django.db.models import Q
from django.utils import timezone

from grading.models import TranscriptAccessRequest
from grading.services.transcript_pdf import build_official_transcript_pdf_bytes
from settings.models import GradingSettings
from students.models import Student
from students.services.student_status import compute_is_enrolled

logger = logging.getLogger(__name__)


def get_grading_settings() -> GradingSettings | None:
    return GradingSettings.objects.first()


def get_default_download_days(settings_obj: GradingSettings | None = None) -> int:
    settings_obj = settings_obj or get_grading_settings()
    if not settings_obj:
        return 3
    return max(int(settings_obj.transcript_download_days or 3), 1)


def _student_matches_user(student: Student, user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_student_user", False):
        linked = user.get_student()
        return linked is not None and str(linked.id) == str(student.id)
    return False


def _is_transcript_admin(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if getattr(user, "is_admin", False):
        return True
    role = (getattr(user, "role", None) or "").upper()
    if role in {"REGISTRAR", "SCHOOL_ADMINISTRATOR"}:
        return True
    privileges = set(getattr(user, "privileges", None) or [])
    return "GRADING_APPROVE" in privileges or "GRADING_ENTER" in privileges


def _student_eligible_for_self_service(student: Student, settings_obj: GradingSettings) -> bool:
    if not settings_obj.allow_student_transcript_download:
        return False
    scope = settings_obj.student_transcript_download_scope or "enrolled"
    if scope == "enrolled":
        return compute_is_enrolled(student)
    return student.status not in {"withdrawn", "deleted", "inactive"}


def get_active_approved_access(student: Student) -> TranscriptAccessRequest | None:
    qs = (
        TranscriptAccessRequest.objects.filter(
            student=student,
            status=TranscriptAccessRequest.Status.APPROVED,
        )
        .order_by("-reviewed_at", "-created_at")
    )
    for access in qs:
        access.mark_expired_if_needed()
        if access.is_download_active:
            return access
    return None


def get_pending_request(student: Student) -> TranscriptAccessRequest | None:
    return (
        TranscriptAccessRequest.objects.filter(
            student=student,
            status=TranscriptAccessRequest.Status.PENDING,
        )
        .order_by("-created_at")
        .first()
    )


def can_download_transcript(user, student: Student) -> tuple[bool, str]:
    if _is_transcript_admin(user):
        return True, "admin"

    active_access = get_active_approved_access(student)
    if active_access and active_access.allow_download:
        if _student_matches_user(student, user):
            return True, "approved_access"

    settings_obj = get_grading_settings()
    if settings_obj and _student_eligible_for_self_service(student, settings_obj):
        if _student_matches_user(student, user):
            return True, "self_service"

    return False, "not_authorized"


def build_access_status(user, student: Student) -> dict:
    settings_obj = get_grading_settings()
    is_admin = _is_transcript_admin(user)
    is_owner = _student_matches_user(student, user)
    pending = get_pending_request(student)
    active = get_active_approved_access(student)

    can_download, reason = can_download_transcript(user, student)
    self_service_enabled = bool(
        settings_obj
        and settings_obj.allow_student_transcript_download
        and _student_eligible_for_self_service(student, settings_obj)
    )

    return {
        "can_download": can_download,
        "access_reason": reason,
        "is_admin_viewer": is_admin,
        "is_student_owner": is_owner,
        "self_service_enabled": self_service_enabled and is_owner,
        "pending_request": _serialize_access(pending) if pending else None,
        "active_access": _serialize_access(active) if active else None,
        "settings": {
            "allow_student_transcript_download": bool(
                settings_obj and settings_obj.allow_student_transcript_download
            ),
            "student_transcript_download_scope": (
                settings_obj.student_transcript_download_scope if settings_obj else "enrolled"
            ),
            "transcript_download_days": get_default_download_days(settings_obj),
        },
    }


def create_student_request(user, student: Student, student_note: str = "") -> TranscriptAccessRequest:
    if not _student_matches_user(student, user):
        raise PermissionError("You can only request your own transcript.")

    if get_pending_request(student):
        raise ValueError("You already have a pending transcript request.")

    if get_active_approved_access(student):
        raise ValueError("You already have active transcript download access.")

    settings_obj = get_grading_settings()
    if settings_obj and _student_eligible_for_self_service(student, settings_obj):
        raise ValueError("Transcript download is already available for your account.")

    return TranscriptAccessRequest.objects.create(
        student=student,
        status=TranscriptAccessRequest.Status.PENDING,
        source=TranscriptAccessRequest.Source.STUDENT_REQUEST,
        student_note=(student_note or "").strip(),
        requested_by=user,
        created_by=user,
        updated_by=user,
    )


def approve_or_grant_access(
    *,
    student: Student,
    reviewer,
    allow_download: bool,
    send_email: bool,
    download_days: int | None = None,
    admin_note: str = "",
    source: str = TranscriptAccessRequest.Source.ADMIN_GRANT,
    access_request: TranscriptAccessRequest | None = None,
) -> TranscriptAccessRequest:
    if not _is_transcript_admin(reviewer):
        raise PermissionError("Only staff can approve or grant transcript access.")

    if not allow_download and not send_email:
        raise ValueError("Select at least one delivery option: download or email.")

    settings_obj = get_grading_settings()
    days = download_days if download_days is not None else get_default_download_days(settings_obj)
    now = timezone.now()

    if access_request:
        record = access_request
        record.status = TranscriptAccessRequest.Status.APPROVED
        record.allow_download = allow_download
        record.send_email = send_email
        record.admin_note = (admin_note or "").strip()
        record.reviewed_by = reviewer
        record.reviewed_at = now
        record.updated_by = reviewer
        record.download_expires_at = (
            now + timedelta(days=days) if allow_download else None
        )
        record.save()
    else:
        record = TranscriptAccessRequest.objects.create(
            student=student,
            status=TranscriptAccessRequest.Status.APPROVED,
            source=source,
            allow_download=allow_download,
            send_email=send_email,
            admin_note=(admin_note or "").strip(),
            requested_by=reviewer,
            reviewed_by=reviewer,
            reviewed_at=now,
            created_by=reviewer,
            updated_by=reviewer,
            download_expires_at=now + timedelta(days=days) if allow_download else None,
        )

    if send_email and not record.email_sent_at:
        from django.db import connection

        _deliver_transcript_email_async(
            student,
            record,
            schema_name=getattr(connection, "schema_name", None),
        )

    return record


def deny_request(access_request: TranscriptAccessRequest, reviewer, admin_note: str = "") -> TranscriptAccessRequest:
    if not _is_transcript_admin(reviewer):
        raise PermissionError("Only staff can deny transcript requests.")
    if access_request.status != TranscriptAccessRequest.Status.PENDING:
        raise ValueError("Only pending requests can be denied.")

    access_request.status = TranscriptAccessRequest.Status.DENIED
    access_request.admin_note = (admin_note or "").strip()
    access_request.reviewed_by = reviewer
    access_request.reviewed_at = timezone.now()
    access_request.updated_by = reviewer
    access_request.save()
    return access_request


def _deliver_transcript_email_async(
    student: Student,
    access: TranscriptAccessRequest,
    *,
    schema_name: str | None = None,
) -> None:
    tenant_schema = schema_name or getattr(connection, "schema_name", None)
    student_id = str(student.id)

    def background_work() -> None:
        from django.db import close_old_connections
        from django_tenants.utils import schema_context

        close_old_connections()
        if not tenant_schema:
            logger.warning(
                "Transcript email skipped: missing tenant schema for student %s",
                student_id,
            )
            return

        try:
            with schema_context(tenant_schema):
                student_obj = Student.objects.get(id=student_id)
                pdf_bytes = build_official_transcript_pdf_bytes(student_obj)
                recipient = (student_obj.email or "").strip()
                if not recipient:
                    logger.warning(
                        "Transcript email skipped: no student email for %s",
                        student_id,
                    )
                    return

                subject = f"Official Transcript - {student_obj.get_full_name()}"
                body = (
                    f"Dear {student_obj.get_full_name()},\n\n"
                    "Please find your official transcript attached.\n\n"
                    "This document is official only when signed by a school official "
                    "and embossed with the school seal.\n\n"
                    "Best regards,\nSchool Administration"
                )
                email = EmailMessage(
                    subject=subject,
                    body=body,
                    from_email=django_settings.DEFAULT_FROM_EMAIL,
                    to=[recipient],
                )
                email.attach(
                    f"Official_Transcript_{student_obj.id_number}.pdf",
                    pdf_bytes,
                    "application/pdf",
                )
                email.send()

                access_record = TranscriptAccessRequest.objects.get(id=access.id)
                access_record.email_sent_at = timezone.now()
                access_record.save(update_fields=["email_sent_at", "updated_at"])
        except Exception:
            logger.exception("Failed to email transcript for student %s", student_id)

    thread = threading.Thread(target=background_work)
    thread.daemon = True
    thread.start()


def _serialize_access(access: TranscriptAccessRequest | None) -> dict | None:
    if not access:
        return None
    return {
        "id": str(access.id),
        "status": access.status,
        "source": access.source,
        "allow_download": access.allow_download,
        "send_email": access.send_email,
        "download_expires_at": (
            access.download_expires_at.isoformat() if access.download_expires_at else None
        ),
        "email_sent_at": access.email_sent_at.isoformat() if access.email_sent_at else None,
        "student_note": access.student_note,
        "admin_note": access.admin_note,
        "created_at": access.created_at.isoformat() if access.created_at else None,
        "reviewed_at": access.reviewed_at.isoformat() if access.reviewed_at else None,
        "is_download_active": access.is_download_active,
    }


def list_transcript_requests(*, status: str | None = None, student_id: str | None = None) -> list[dict]:
    qs = TranscriptAccessRequest.objects.select_related(
        "student",
        "requested_by",
        "reviewed_by",
    ).order_by("-created_at")

    if status:
        qs = qs.filter(status=status)
    if student_id:
        qs = qs.filter(Q(student_id=student_id) | Q(student__id_number=student_id))

    results = []
    for access in qs[:200]:
        access.mark_expired_if_needed()
        results.append(
            {
                **_serialize_access(access),
                "student": {
                    "id": str(access.student_id),
                    "id_number": access.student.id_number,
                    "full_name": access.student.get_full_name(),
                },
            }
        )
    return results

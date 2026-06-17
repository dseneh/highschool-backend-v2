"""In-app and email notifications for transcript access workflow."""

from __future__ import annotations

import logging

from grading.models import TranscriptAccessRequest
from notifications.models import NotificationRule
from notifications.services.audience import get_tenant_user_queryset
from students.models import Student

logger = logging.getLogger(__name__)

_TRANSCRIPT_QUEUE_PATH = "/grading/transcript-requests"
_STUDENT_REPORTS_PATH = "/my-reports"
_TRANSCRIPT_ADMIN_ROLES = {"admin", "registrar", "superadmin", "school_administrator"}
_TRANSCRIPT_ADMIN_PRIVILEGES = {"GRADING_APPROVE", "GRADING_ENTER"}


def _student_display_name(student: Student) -> str:
    if hasattr(student, "get_full_name"):
        return student.get_full_name()
    return str(student)


def _note_suffix(note: str) -> str:
    cleaned = (note or "").strip()
    if not cleaned:
        return ""
    return f' Note: "{cleaned}"'


def _resolve_transcript_admin_user_ids() -> list[str]:
    """Match the same staff who can review transcript requests."""
    recipient_ids: set = set()
    tenant_users = get_tenant_user_queryset()

    for user in tenant_users.iterator():
        role = (getattr(user, "role", None) or "").lower()
        if role in _TRANSCRIPT_ADMIN_ROLES:
            recipient_ids.add(user.id)
            continue
        if getattr(user, "is_superuser", False) or getattr(user, "is_admin", False):
            recipient_ids.add(user.id)
            continue
        try:
            privileges = set(user.get_privileges() or [])
        except Exception:
            privileges = set()
        if privileges & _TRANSCRIPT_ADMIN_PRIVILEGES:
            recipient_ids.add(user.id)

    return [str(user_id) for user_id in recipient_ids]


def _student_user_audience(student: Student) -> dict:
    """Target the student's portal account directly when possible."""
    id_number = (getattr(student, "user_account_id_number", None) or "").strip()
    if id_number:
        user_ids = list(
            get_tenant_user_queryset()
            .filter(id_number=id_number)
            .values_list("id", flat=True)
        )
        if user_ids:
            return {"scope": "user_ids", "user_ids": [str(uid) for uid in user_ids]}

    student_id_number = (getattr(student, "id_number", None) or "").strip()
    if student_id_number:
        user_ids = list(
            get_tenant_user_queryset()
            .filter(id_number=student_id_number)
            .values_list("id", flat=True)
        )
        if user_ids:
            return {"scope": "user_ids", "user_ids": [str(uid) for uid in user_ids]}

    return {"scope": "students", "student_ids": [str(student.id)]}


def _dispatch(
    event_type: str,
    *,
    context: dict,
    audience: dict,
    created_by,
    action_url: str = "",
) -> None:
    try:
        from notifications.services.dispatch import dispatch_from_rule

        dispatch_from_rule(
            event_type,
            {
                **context,
                "audience": audience,
                "created_by": created_by,
                "action_url": action_url,
            },
        )
    except Exception:
        logger.exception("Transcript notification failed (%s)", event_type)


def notify_transcript_requested(
    access: TranscriptAccessRequest,
    student: Student,
    requested_by,
) -> None:
    admin_user_ids = _resolve_transcript_admin_user_ids()
    if not admin_user_ids:
        logger.warning(
            "No transcript admin recipients resolved for student %s request %s",
            student.id,
            access.id,
        )
        return

    student_name = _student_display_name(student)
    _dispatch(
        NotificationRule.EventType.TRANSCRIPT_REQUESTED,
        context={
            "student_name": student_name,
            "student_id_number": student.id_number,
            "student_note_suffix": _note_suffix(access.student_note),
        },
        audience={"scope": "user_ids", "user_ids": admin_user_ids},
        created_by=requested_by,
        action_url=_TRANSCRIPT_QUEUE_PATH,
    )


def notify_transcript_approved(
    access: TranscriptAccessRequest,
    student: Student,
    reviewer,
) -> None:
    delivery_parts = []
    if access.allow_download:
        delivery_parts.append("download your official transcript from the portal")
    if access.send_email:
        delivery_parts.append("receive a copy by email")
    delivery_hint = (
        " and ".join(delivery_parts)
        if delivery_parts
        else "view your transcript access in the portal"
    )

    audience = _student_user_audience(student)
    _dispatch(
        NotificationRule.EventType.TRANSCRIPT_APPROVED,
        context={
            "student_name": _student_display_name(student),
            "delivery_hint": delivery_hint,
        },
        audience=audience,
        created_by=reviewer,
        action_url=_STUDENT_REPORTS_PATH,
    )


def notify_transcript_denied(
    access: TranscriptAccessRequest,
    student: Student,
    reviewer,
) -> None:
    _dispatch(
        NotificationRule.EventType.TRANSCRIPT_DENIED,
        context={
            "student_name": _student_display_name(student),
            "admin_note_suffix": _note_suffix(access.admin_note),
        },
        audience=_student_user_audience(student),
        created_by=reviewer,
        action_url=_STUDENT_REPORTS_PATH,
    )

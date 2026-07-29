from __future__ import annotations

from datetime import date

from django.utils import timezone

from academics.services.school_days import iter_instructional_days
from common.status import AttendanceStatus, EnrollmentStatus
from students.models import Attendance, DisciplinaryAttendanceImpact, Enrollment

RESOLUTION_RESTORE_PREVIOUS = "restore_previous"
RESOLUTION_KEEP_OVERRIDDEN = "keep_overridden"
ALLOWED_RESOLUTIONS = {
    RESOLUTION_RESTORE_PREVIOUS,
    RESOLUTION_KEEP_OVERRIDDEN,
}


def _resolve_enrollment_for_day(student, attendance_date: date):
    return (
        Enrollment.objects.filter(
            student=student,
            status=EnrollmentStatus.ENROLLED,
            academic_year__start_date__lte=attendance_date,
            academic_year__end_date__gte=attendance_date,
        )
        .order_by("-academic_year__start_date")
        .first()
    )


def _build_note_marker(discipline_action):
    return f"[Discipline:{discipline_action.id}]"


def apply_attendance_effect_for_discipline(discipline_action, user=None):
    action_type = discipline_action.action_type
    if not action_type or not action_type.attendance_effect_enabled:
        return {"school_days_considered": 0, "attendance_rows_updated": 0}

    target_status = action_type.attendance_effect_status
    marker = _build_note_marker(discipline_action)

    attendance_rows_updated = 0
    school_days = list(
        iter_instructional_days(discipline_action.start_date, discipline_action.end_date)
    )

    for school_day in school_days:
        enrollment = _resolve_enrollment_for_day(discipline_action.student, school_day)
        if not enrollment:
            continue

        attendance = Attendance.objects.filter(enrollment=enrollment, date=school_day).first()
        original_status = attendance.status if attendance else None
        was_created = attendance is None

        if attendance:
            if attendance.status != target_status:
                attendance.status = target_status
                note = (attendance.notes or "").strip()
                if marker not in note:
                    attendance.notes = f"{note}\n{marker} Attendance set by discipline action.".strip()
                if user is not None:
                    attendance.updated_by = user
                    attendance.save(update_fields=["status", "notes", "updated_by", "updated_at"])
                else:
                    attendance.save(update_fields=["status", "notes", "updated_at"])
                attendance_rows_updated += 1
        else:
            attendance = Attendance.objects.create(
                enrollment=enrollment,
                date=school_day,
                status=target_status,
                notes=f"{marker} Attendance set by discipline action.",
                created_by=user,
                updated_by=user,
            )
            attendance_rows_updated += 1

        impact, created = DisciplinaryAttendanceImpact.objects.get_or_create(
            discipline_action=discipline_action,
            effective_date=school_day,
            defaults={
                "attendance": attendance,
                "original_status": original_status,
                "applied_status": target_status,
                "was_created": was_created,
                "resolution": DisciplinaryAttendanceImpact.Resolution.PENDING,
                "resolved_at": None,
                "created_by": user,
                "updated_by": user,
            },
        )

        if not created:
            update_fields = []
            if impact.attendance_id != attendance.id:
                impact.attendance = attendance
                update_fields.append("attendance")
            if impact.applied_status != target_status:
                impact.applied_status = target_status
                update_fields.append("applied_status")
            if impact.was_created != was_created:
                impact.was_created = was_created
                update_fields.append("was_created")
            if impact.resolution != DisciplinaryAttendanceImpact.Resolution.PENDING:
                impact.resolution = DisciplinaryAttendanceImpact.Resolution.PENDING
                update_fields.append("resolution")
            if impact.resolved_at is not None:
                impact.resolved_at = None
                update_fields.append("resolved_at")
            if update_fields:
                if user is not None:
                    impact.updated_by = user
                    update_fields.append("updated_by")
                impact.save(update_fields=[*update_fields, "updated_at"])

    return {
        "school_days_considered": len(school_days),
        "attendance_rows_updated": attendance_rows_updated,
    }


def count_unresolved_attendance_impacts_after(discipline_action, cutoff_date: date):
    return discipline_action.attendance_impacts.filter(
        effective_date__gt=cutoff_date,
        resolution=DisciplinaryAttendanceImpact.Resolution.PENDING,
    ).count()


def resolve_attendance_impacts_after(
    discipline_action,
    cutoff_date: date,
    *,
    resolution: str,
    user=None,
):
    impacts = discipline_action.attendance_impacts.select_related("attendance").filter(
        effective_date__gt=cutoff_date,
        resolution=DisciplinaryAttendanceImpact.Resolution.PENDING,
    )

    resolved_count = 0
    now = timezone.now()

    for impact in impacts:
        attendance = impact.attendance

        if resolution == RESOLUTION_RESTORE_PREVIOUS:
            if impact.was_created and not impact.original_status:
                if attendance:
                    attendance.delete()
                impact.attendance = None
                impact.resolution = DisciplinaryAttendanceImpact.Resolution.DELETED
            else:
                if attendance:
                    attendance.status = impact.original_status or AttendanceStatus.PRESENT.value
                    if user is not None:
                        attendance.updated_by = user
                        attendance.save(update_fields=["status", "updated_by", "updated_at"])
                    else:
                        attendance.save(update_fields=["status", "updated_at"])
                impact.resolution = DisciplinaryAttendanceImpact.Resolution.RESTORED
        else:
            impact.resolution = DisciplinaryAttendanceImpact.Resolution.KEPT

        impact.resolved_at = now
        if user is not None:
            impact.updated_by = user
            impact.save(update_fields=["attendance", "resolution", "resolved_at", "updated_by", "updated_at"])
        else:
            impact.save(update_fields=["attendance", "resolution", "resolved_at", "updated_at"])
        resolved_count += 1

    return resolved_count

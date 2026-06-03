"""
Shared rules for student lifecycle vs enrollment status.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from django.db.models import Exists, OuterRef, QuerySet

from common.status import EnrollmentStatus, StudentStatus

if TYPE_CHECKING:
    from academics.models import AcademicYear
    from students.models import Enrollment, Student

# Person-level exits / blocks (student.status).
TERMINAL_LIFECYCLE_STATUSES = frozenset(
    {
        StudentStatus.INACTIVE,
        StudentStatus.GRADUATED,
        StudentStatus.SUSPENDED,
        StudentStatus.DELETED,
        StudentStatus.WITHDRAWN,
        StudentStatus.TRANSFERRED,
    }
)

# Deprecated on student row — treat like active until data is migrated.
LEGACY_STUDENT_OPERATIONAL_STATUSES = frozenset(
    {
        StudentStatus.ACTIVE,
        StudentStatus.ENROLLED,
    }
)

# In-progress or active seat for the current academic year.
SEAT_ENROLLMENT_STATUSES = frozenset(
    {
        EnrollmentStatus.PENDING,
        EnrollmentStatus.ENROLLED,
    }
)

# Actively attending this year (enrollment.status source of truth for is_enrolled).
ENROLLED_ROW_STATUSES = frozenset(
    {
        EnrollmentStatus.ENROLLED,
    }
)

YEAR_END_ENROLLMENT_STATUSES = frozenset(
    {
        EnrollmentStatus.COMPLETED,
    }
)

ACTIVE_ENROLLMENT_STATUSES = SEAT_ENROLLMENT_STATUSES


def normalize_lifecycle_status(status: str | None) -> str:
    """Prefer active on student; enrolled is legacy."""
    if not status:
        return StudentStatus.ACTIVE
    value = status.lower().strip()
    if value == StudentStatus.ENROLLED:
        return StudentStatus.ACTIVE
    return value


def normalize_enrollment_status(status: str | None) -> str:
    """Map client values to enrollment.status for creates/updates."""
    if not status:
        return EnrollmentStatus.ENROLLED
    value = status.lower().strip()
    if value == "active":
        return EnrollmentStatus.ENROLLED
    if value in EnrollmentStatus.all():
        return value
    return EnrollmentStatus.ENROLLED


def is_terminal_lifecycle(status: str | None) -> bool:
    if not status:
        return False
    return status.lower() in TERMINAL_LIFECYCLE_STATUSES


def is_operational_lifecycle(status: str | None) -> bool:
    if not status:
        return False
    return status.lower() in LEGACY_STUDENT_OPERATIONAL_STATUSES


def is_active_enrollment_status(status: str | None) -> bool:
    if not status:
        return False
    return status.lower() in ACTIVE_ENROLLMENT_STATUSES


def resolve_current_enrollment(
    student: "Student",
    academic_year: Optional["AcademicYear"] = None,
) -> Optional["Enrollment"]:
    if academic_year is not None:
        return student.enrollments.filter(academic_year=academic_year).first()

    from students.models.student import get_current_academic_year

    year = get_current_academic_year()
    if not year:
        return None
    return student.enrollments.filter(academic_year=year).first()


def compute_is_enrolled(
    student: "Student",
    current_enrollment: Optional["Enrollment"] = None,
    academic_year: Optional["AcademicYear"] = None,
) -> bool:
    lifecycle = (student.status or "").lower()
    if is_terminal_lifecycle(lifecycle):
        return False

    enrollment = current_enrollment
    if enrollment is None:
        enrollment = resolve_current_enrollment(student, academic_year=academic_year)
    if not enrollment:
        return False

    return (enrollment.status or "").lower() in ENROLLED_ROW_STATUSES


def compute_display_status(
    lifecycle_status: str | None,
    *,
    enrollment_status: str | None = None,
) -> str:
    """API `status` mirrors UI: lifecycle when terminal, else enrollment row status."""
    if is_terminal_lifecycle(lifecycle_status):
        return lifecycle_status or ""
    if enrollment_status:
        return enrollment_status
    return "not enrolled"


def apply_status_fields_to_response(
    response: dict,
    student: "Student",
    current_enrollment: Optional["Enrollment"] = None,
    academic_year: Optional["AcademicYear"] = None,
) -> dict:
    lifecycle_status = student.status or ""
    enrollment_status = (
        current_enrollment.status if current_enrollment is not None else None
    )
    is_enrolled = compute_is_enrolled(
        student,
        current_enrollment=current_enrollment,
        academic_year=academic_year,
    )
    display_status = compute_display_status(
        lifecycle_status,
        enrollment_status=enrollment_status,
    )

    response["lifecycle_status"] = lifecycle_status
    response["enrollment_status"] = enrollment_status
    response["is_enrolled"] = is_enrolled
    response["status"] = display_status
    return response


def _enrollment_exists_subquery(*, statuses, academic_year_id=None, academic_year=None):
    from students.models import Enrollment

    filters = {
        "student_id": OuterRef("pk"),
        "status__in": statuses,
    }
    if academic_year is not None:
        filters["academic_year"] = academic_year
    elif academic_year_id:
        filters["academic_year_id"] = academic_year_id
    else:
        filters["academic_year__current"] = True

    return Exists(Enrollment.objects.filter(**filters))


def seat_enrollment_exists(*, academic_year_id=None, academic_year=None):
    return _enrollment_exists_subquery(
        statuses=SEAT_ENROLLMENT_STATUSES,
        academic_year_id=academic_year_id,
        academic_year=academic_year,
    )


def enrolled_row_exists(*, academic_year_id=None, academic_year=None):
    return _enrollment_exists_subquery(
        statuses=ENROLLED_ROW_STATUSES,
        academic_year_id=academic_year_id,
        academic_year=academic_year,
    )


def active_enrollment_exists(*, academic_year_id=None, academic_year=None):
    """Backward-compatible alias for seat enrollment."""
    return seat_enrollment_exists(
        academic_year_id=academic_year_id,
        academic_year=academic_year,
    )


def filter_students_enrolled(
    students: QuerySet,
    *,
    academic_year=None,
) -> QuerySet:
    """Students with enrollment.status = enrolled for the year."""
    return (
        students.filter(enrolled_row_exists(academic_year=academic_year))
        .exclude(status__in=TERMINAL_LIFECYCLE_STATUSES)
        .distinct()
    )


def filter_students_pending(
    students: QuerySet,
    *,
    academic_year=None,
) -> QuerySet:
    return (
        students.filter(
            _enrollment_exists_subquery(
                statuses=[EnrollmentStatus.PENDING],
                academic_year=academic_year,
            )
        )
        .exclude(status__in=TERMINAL_LIFECYCLE_STATUSES)
        .distinct()
    )


def filter_students_year_completed(
    students: QuerySet,
    *,
    academic_year=None,
) -> QuerySet:
    return (
        students.filter(
            _enrollment_exists_subquery(
                statuses=list(YEAR_END_ENROLLMENT_STATUSES),
                academic_year=academic_year,
            )
        )
        .exclude(status__in=TERMINAL_LIFECYCLE_STATUSES)
        .distinct()
    )


def filter_students_not_enrolled(
    students: QuerySet,
    *,
    academic_year=None,
) -> QuerySet:
    """Operational lifecycle students without a pending/enrolled seat for the year."""
    return (
        students.exclude(seat_enrollment_exists(academic_year=academic_year))
        .exclude(status__in=TERMINAL_LIFECYCLE_STATUSES)
        .distinct()
    )


def filter_students_by_enrollment_row_status(
    students: QuerySet,
    statuses: list[str],
    *,
    academic_year=None,
) -> QuerySet:
    normalized = []
    for raw in statuses:
        value = (raw or "").lower().strip()
        if value in EnrollmentStatus.all():
            normalized.append(value)
    if not normalized:
        return students.none()
    return (
        students.filter(
            _enrollment_exists_subquery(
                statuses=normalized,
                academic_year=academic_year,
            )
        )
        .exclude(status__in=TERMINAL_LIFECYCLE_STATUSES)
        .distinct()
    )


def build_student_list_stats(students: QuerySet) -> dict:
    """
    Stats aligned with display status rules (see docs/STUDENT_STATUS_CONTRACT.md).
    """
    from django.db.models import Count

    stats: dict = {"total": students.distinct().count()}

    stats["enrolled"] = filter_students_enrolled(students).count()
    stats["pending"] = filter_students_pending(students).count()
    stats["completed"] = filter_students_year_completed(students).count()
    stats["not_enrolled"] = filter_students_not_enrolled(students).count()

    stats["enrolled_this_year"] = stats["enrolled"]
    stats["not_enrolled_this_year"] = stats["not_enrolled"]

    for row in (
        students.filter(status__in=TERMINAL_LIFECYCLE_STATUSES)
        .values("status")
        .annotate(count=Count("id", distinct=True))
        .order_by()
    ):
        key = row.get("status")
        if key:
            stats[key] = row.get("count") or 0

    for row in (
        students.exclude(status__in=TERMINAL_LIFECYCLE_STATUSES)
        .exclude(seat_enrollment_exists())
        .values("status")
        .annotate(count=Count("id", distinct=True))
        .order_by()
    ):
        key = row.get("status")
        if key and key not in stats:
            stats[key] = row.get("count") or 0

    return stats

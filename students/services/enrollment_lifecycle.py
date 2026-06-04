"""
Per-student enrollment lifecycle transitions (year-end, graduate, transfer).
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Optional

from academics.models import GradeLevel
from common.status import EnrollmentStatus, StudentStatus, YearEndOutcome
from students.services.student_status import resolve_current_enrollment

if TYPE_CHECKING:
    from students.models import Enrollment, Student


class EnrollmentLifecycleError(Exception):
    """Business rule violation for enrollment lifecycle actions."""


def resolve_next_grade_level(
    grade_level: GradeLevel,
    outcome: str,
) -> Optional[GradeLevel]:
    """
    Placement for the next academic year after year-end closure.
    Returns None when the student should graduate instead of promoting.
    """
    normalized = (outcome or "").lower().strip()
    if normalized == YearEndOutcome.REPEATED:
        return grade_level

    if normalized != YearEndOutcome.PROMOTED:
        return None

    return (
        GradeLevel.objects.filter(
            active=True,
            division_id=grade_level.division_id,
            level=grade_level.level + 1,
        )
        .order_by("level")
        .first()
    )


def _require_enrolled_enrollment(enrollment: Optional["Enrollment"]) -> "Enrollment":
    if enrollment is None:
        raise EnrollmentLifecycleError(
            "Student has no enrollment for the current academic year."
        )
    if (enrollment.status or "").lower() != EnrollmentStatus.ENROLLED:
        raise EnrollmentLifecycleError(
            f"Current enrollment status is '{enrollment.status}'. "
            "Only enrolled students can use this action."
        )
    return enrollment


def close_enrollment_year(
    student: "Student",
    outcome: str,
    *,
    academic_year=None,
) -> "Enrollment":
    """
    Close the current academic year with promoted or repeated outcome.
    Sets enrollment.status = completed and next_grade_level.
    """
    normalized = (outcome or "").lower().strip()
    if normalized not in YearEndOutcome.close_year_outcomes():
        raise EnrollmentLifecycleError(
            "outcome must be 'promoted' or 'repeated'."
        )

    enrollment = _require_enrolled_enrollment(
        resolve_current_enrollment(student, academic_year=academic_year)
    )

    next_grade = resolve_next_grade_level(enrollment.grade_level, normalized)
    if normalized == YearEndOutcome.PROMOTED and next_grade is None:
        raise EnrollmentLifecycleError(
            "No higher grade level is configured. Use graduate instead."
        )

    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.year_end_outcome = normalized
    enrollment.next_grade_level = next_grade
    enrollment.save(
        update_fields=["status", "year_end_outcome", "next_grade_level"]
    )

    if (student.status or "").lower() in (
        StudentStatus.WITHDRAWN,
        StudentStatus.TRANSFERRED,
        StudentStatus.ENROLLED,
    ):
        student.status = StudentStatus.ACTIVE
        student.save(update_fields=["status"])

    return enrollment


def graduate_student(
    student: "Student",
    *,
    graduation_date: Optional[date] = None,
    academic_year=None,
) -> "Enrollment":
    enrollment = _require_enrolled_enrollment(
        resolve_current_enrollment(student, academic_year=academic_year)
    )

    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.year_end_outcome = YearEndOutcome.GRADUATED
    enrollment.next_grade_level = None
    enrollment.save(
        update_fields=["status", "year_end_outcome", "next_grade_level"]
    )

    student.status = StudentStatus.GRADUATED
    update_fields = ["status"]
    if graduation_date is not None:
        student.date_of_graduation = graduation_date
        update_fields.append("date_of_graduation")
    student.save(update_fields=update_fields)

    return enrollment


def transfer_out_student(
    student: "Student",
    *,
    transfer_date: Optional[date] = None,
    reason: Optional[str] = None,
    academic_year=None,
) -> Optional["Enrollment"]:
    enrollment = resolve_current_enrollment(student, academic_year=academic_year)

    student.status = StudentStatus.TRANSFERRED
    student.withdrawal_date = transfer_date
    student.withdrawal_reason = reason
    student.save(
        update_fields=["status", "withdrawal_date", "withdrawal_reason"]
    )

    if enrollment and (enrollment.status or "").lower() == EnrollmentStatus.ENROLLED:
        enrollment.status = EnrollmentStatus.WITHDRAWN
        enrollment.year_end_outcome = YearEndOutcome.TRANSFERRED
        enrollment.next_grade_level = None
        enrollment.save(
            update_fields=["status", "year_end_outcome", "next_grade_level"]
        )
        return enrollment

    return enrollment


def mid_year_promote_student(
    student: "Student",
    *,
    academic_year=None,
) -> "Enrollment":
    """
    Advance a student to the next grade level during the current academic year.
    Enrollment stays enrolled; section moves to an active section in the new grade.
    """
    from academics.models import Section

    enrollment = _require_enrolled_enrollment(
        resolve_current_enrollment(student, academic_year=academic_year)
    )

    next_grade = resolve_next_grade_level(
        enrollment.grade_level, YearEndOutcome.PROMOTED
    )
    if next_grade is None:
        raise EnrollmentLifecycleError(
            "No higher grade level is configured. Use graduate or year-end promote instead."
        )

    section = next_grade.sections.filter(active=True).order_by("name").first()
    if not section:
        section = Section.objects.create(
            grade_level=next_grade,
            name="General",
        )

    enrollment.grade_level = next_grade
    enrollment.section = section
    enrollment.next_grade_level = resolve_next_grade_level(
        next_grade, YearEndOutcome.PROMOTED
    )
    enrollment.save(
        update_fields=["grade_level", "section", "next_grade_level"]
    )

    if (student.status or "").lower() in (
        StudentStatus.WITHDRAWN,
        StudentStatus.TRANSFERRED,
        StudentStatus.ENROLLED,
    ):
        student.status = StudentStatus.ACTIVE
        student.save(update_fields=["status"])

    return enrollment


def undo_year_end_promotion(
    student: "Student",
    *,
    academic_year=None,
) -> "Enrollment":
    """
    Revert a completed year-end promote/repeat back to an active enrolled seat.
    """
    enrollment = resolve_current_enrollment(student, academic_year=academic_year)
    if enrollment is None:
        raise EnrollmentLifecycleError(
            "Student has no enrollment for the current academic year."
        )

    status = (enrollment.status or "").lower().strip()
    outcome = (enrollment.year_end_outcome or "").lower().strip()

    if status != EnrollmentStatus.COMPLETED:
        raise EnrollmentLifecycleError(
            "Only completed year-end enrollments can be undone from this action."
        )
    if outcome not in YearEndOutcome.close_year_outcomes():
        raise EnrollmentLifecycleError(
            "Only promoted or repeated year-end outcomes can be undone."
        )

    enrollment.status = EnrollmentStatus.ENROLLED
    enrollment.year_end_outcome = None
    enrollment.next_grade_level = None
    enrollment.save(
        update_fields=["status", "year_end_outcome", "next_grade_level"]
    )

    if (student.status or "").lower() in (
        StudentStatus.WITHDRAWN,
        StudentStatus.TRANSFERRED,
        StudentStatus.ENROLLED,
    ):
        student.status = StudentStatus.ACTIVE
        student.save(update_fields=["status"])

    return enrollment


def undo_mid_year_promotion(
    student: "Student",
    *,
    academic_year=None,
) -> "Enrollment":
    """
    Move a student back one grade level within the current year (reverses mid-year promote).
    """
    from academics.models import Section

    enrollment = _require_enrolled_enrollment(
        resolve_current_enrollment(student, academic_year=academic_year)
    )

    current_grade = enrollment.grade_level
    if current_grade is None or current_grade.level is None or current_grade.level <= 1:
        raise EnrollmentLifecycleError(
            "Student is already in the lowest grade; cannot undo mid-year promotion."
        )

    previous_grade = (
        GradeLevel.objects.filter(
            active=True,
            division_id=current_grade.division_id,
            level=current_grade.level - 1,
        )
        .order_by("level")
        .first()
    )
    if previous_grade is None:
        raise EnrollmentLifecycleError(
            "Previous grade level is not configured."
        )

    section = previous_grade.sections.filter(active=True).order_by("name").first()
    if not section:
        section = Section.objects.create(
            grade_level=previous_grade,
            name="General",
        )

    enrollment.grade_level = previous_grade
    enrollment.section = section
    enrollment.next_grade_level = resolve_next_grade_level(
        previous_grade, YearEndOutcome.PROMOTED
    )
    enrollment.save(
        update_fields=["grade_level", "section", "next_grade_level"]
    )

    return enrollment

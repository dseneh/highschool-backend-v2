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

    progression_steps = {
        YearEndOutcome.PROMOTED: 1,
        YearEndOutcome.DOUBLE_PROMOTED: 2,
    }.get(normalized)
    if progression_steps is None:
        return None

    candidates = list(
        GradeLevel.objects.filter(active=True, level__gt=grade_level.level)
        .order_by("level", "name")
    )
    if len(candidates) < progression_steps:
        return None
    return candidates[progression_steps - 1]


def get_year_end_outcome_options(grade_level: GradeLevel) -> list[dict]:
    """Return valid year-end outcomes and their configured next placements."""
    options = [
        {
            "value": YearEndOutcome.REPEATED,
            "label": "Repeating",
            "next_grade_level": grade_level,
        },
        {
            "value": YearEndOutcome.WITHDRAWN,
            "label": "Withdrawn",
            "next_grade_level": None,
        },
    ]
    promoted = resolve_next_grade_level(grade_level, YearEndOutcome.PROMOTED)
    if promoted is not None:
        options.append(
            {
                "value": YearEndOutcome.PROMOTED,
                "label": "Promoted",
                "next_grade_level": promoted,
            }
        )
    double_promoted = resolve_next_grade_level(
        grade_level, YearEndOutcome.DOUBLE_PROMOTED
    )
    if double_promoted is not None:
        options.append(
            {
                "value": YearEndOutcome.DOUBLE_PROMOTED,
                "label": "Double Promoted",
                "next_grade_level": double_promoted,
            }
        )
    if promoted is None:
        options.append(
            {
                "value": YearEndOutcome.GRADUATED,
                "label": "Graduated",
                "next_grade_level": None,
            }
        )
    return options


def resolve_year_end_placement(
    grade_level: GradeLevel,
    outcome: str,
    next_grade_level_id=None,
) -> tuple[str, Optional[GradeLevel]]:
    """Resolve the final year-end outcome and next placement from grade order.

    A promotion from the highest configured grade becomes graduation. This
    deliberately uses the school's configured grade-level ordering rather than
    grade IDs or a required contiguous numeric sequence.
    """
    normalized = (outcome or "").lower().strip()
    if normalized == YearEndOutcome.REPEATED:
        if next_grade_level_id and str(next_grade_level_id) != str(grade_level.pk):
            raise EnrollmentLifecycleError(
                "A repeating student must remain in the current grade level."
            )
        return normalized, grade_level
    if normalized == YearEndOutcome.PROMOTED:
        if next_grade_level_id:
            next_grade = GradeLevel.objects.filter(
                pk=next_grade_level_id,
                active=True,
                level__gt=grade_level.level,
            ).first()
            if next_grade is None:
                raise EnrollmentLifecycleError(
                    "The selected next grade must be an active configured grade above the current grade."
                )
            return normalized, next_grade
        next_grade = resolve_next_grade_level(grade_level, normalized)
        if next_grade is None:
            return YearEndOutcome.GRADUATED, None
        return normalized, next_grade
    if normalized == YearEndOutcome.DOUBLE_PROMOTED:
        expected_next_grade = resolve_next_grade_level(grade_level, normalized)
        if expected_next_grade is None:
            raise EnrollmentLifecycleError(
                "Double promotion requires at least two higher configured grade levels."
            )
        if next_grade_level_id and str(next_grade_level_id) != str(expected_next_grade.pk):
            raise EnrollmentLifecycleError(
                "Double promotion must use the second configured grade above the current grade."
            )
        return normalized, expected_next_grade
    if normalized == YearEndOutcome.GRADUATED:
        if resolve_next_grade_level(grade_level, YearEndOutcome.PROMOTED) is not None:
            raise EnrollmentLifecycleError(
                "Graduation is only available from the highest configured grade level."
            )
        return normalized, None
    if normalized in {YearEndOutcome.WITHDRAWN, YearEndOutcome.TRANSFERRED}:
        return normalized, None
    raise EnrollmentLifecycleError("Unsupported year-end outcome.")


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
    next_grade_level_id=None,
) -> "Enrollment":
    """
    Close the current academic year with a progression or repeat outcome.
    Sets enrollment.status = completed and next_grade_level.
    """
    normalized = (outcome or "").lower().strip()
    if normalized not in YearEndOutcome.close_year_outcomes():
        raise EnrollmentLifecycleError(
            "outcome must be promoted, double_promoted, repeated, or withdrawn."
        )

    enrollment = _require_enrolled_enrollment(
        resolve_current_enrollment(student, academic_year=academic_year)
    )

    resolved_outcome, next_grade = resolve_year_end_placement(
        enrollment.grade_level, normalized, next_grade_level_id
    )

    if normalized == YearEndOutcome.WITHDRAWN:
        enrollment.status = EnrollmentStatus.WITHDRAWN
        enrollment.year_end_outcome = resolved_outcome
        enrollment.next_grade_level = None
        enrollment.save(
            update_fields=["status", "year_end_outcome", "next_grade_level"]
        )
        student.status = StudentStatus.WITHDRAWN
        student.save(update_fields=["status"])
        return enrollment

    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.year_end_outcome = resolved_outcome
    enrollment.next_grade_level = next_grade
    enrollment.save(
        update_fields=["status", "year_end_outcome", "next_grade_level"]
    )

    if resolved_outcome == YearEndOutcome.GRADUATED:
        student.status = StudentStatus.GRADUATED
        student.date_of_graduation = date.today()
        student.save(update_fields=["status", "date_of_graduation"])
    elif (student.status or "").lower() in (
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
            "Only promoted, double-promoted, or repeated year-end outcomes can be undone."
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

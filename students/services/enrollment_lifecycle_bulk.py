"""
Bulk enrollment lifecycle: preview eligibility and apply actions to many students.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from django.db.models import Q

from common.status import EnrollmentStatus, YearEndOutcome
from students.services.enrollment_lifecycle import (
    EnrollmentLifecycleError,
    close_enrollment_year,
    graduate_student,
    mid_year_promote_student,
    resolve_next_grade_level,
    transfer_out_student,
    undo_mid_year_promotion,
    undo_year_end_promotion,
)
from students.services.promotion_rules import (
    get_promotion_rules,
    get_student_overall_average,
    meets_minimum_average,
)
from students.services.student_status import (
    filter_students_enrolled,
    resolve_current_enrollment,
)

BULK_MAX_STUDENTS = 250
CONFIRM_PHRASE = "APPLY"

VALID_BULK_ACTIONS = frozenset(
    {
        "complete_year",
        "graduate",
        "transfer_out",
        "mid_year_promote",
    }
)


def _parse_id_list(values: list | None) -> list[str]:
    if not values:
        return []
    return [str(v).strip() for v in values if str(v).strip()]


def _validate_selection_scope(
    *,
    selection_mode: str,
    student_ids: list[str] | None = None,
    grade_level: str | None = None,
    section: str | None = None,
) -> None:
    if selection_mode == "ids":
        if not _parse_id_list(student_ids):
            raise EnrollmentLifecycleError(
                "selection_mode 'ids' requires at least one student_id."
            )
        return

    if selection_mode == "filters":
        if not (grade_level or "").strip() or not (section or "").strip():
            raise EnrollmentLifecycleError(
                "selection_mode 'filters' requires grade_level and section."
            )
        return

    raise EnrollmentLifecycleError(
        "selection_mode must be 'ids' or 'filters'."
    )


def build_candidate_queryset(
    *,
    student_ids: list[str] | None = None,
    grade_level: str | None = None,
    section: str | None = None,
    search: str | None = None,
):
    """Currently enrolled students (active seat), optionally scoped."""
    from students.models import Student

    qs = filter_students_enrolled(Student.objects.all())

    ids = _parse_id_list(student_ids)
    if ids:
        qs = qs.filter(Q(id_number__in=ids) | Q(id__in=ids))

    if grade_level:
        qs = qs.filter(
            enrollments__academic_year__current=True,
            enrollments__grade_level_id=grade_level,
        )

    if section:
        qs = qs.filter(
            enrollments__academic_year__current=True,
            enrollments__section_id=section,
        )

    if search:
        term = search.strip()
        if term:
            qs = qs.filter(
                Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
                | Q(id_number__icontains=term)
                | Q(middle_name__icontains=term)
            )

    return qs.select_related().prefetch_related(
        "enrollments__grade_level",
        "enrollments__section",
        "enrollments__academic_year",
    ).distinct()


def _enrollment_snapshot(student) -> tuple[str | None, str | None, str | None]:
    enrollment = resolve_current_enrollment(student)
    if not enrollment:
        return None, None, None
    grade = enrollment.grade_level.name if enrollment.grade_level_id else None
    section = enrollment.section.name if enrollment.section_id else None
    return grade, section, enrollment.status


def check_eligibility(
    student,
    action: str,
    *,
    outcome: str | None = None,
    rules: dict | None = None,
) -> tuple[bool, str | None, float | None]:
    from students.services.enrollment_lifecycle import _require_enrolled_enrollment

    rules = rules or get_promotion_rules()
    overall_average: float | None = None

    try:
        if not rules.get("allow_year_closure", True) and action in (
            "complete_year",
            "graduate",
            "transfer_out",
        ):
            return False, "Year closure is disabled in grading settings.", None

        if action == "mid_year_promote" and not rules.get("allow_mid_year_promotion"):
            return (
                False,
                "Mid-year promotion is disabled in grading settings.",
                None,
            )

        enrollment = resolve_current_enrollment(student)
        if action in ("complete_year", "graduate", "mid_year_promote"):
            _require_enrolled_enrollment(enrollment)
        elif action == "transfer_out":
            if not enrollment:
                raise EnrollmentLifecycleError(
                    "Student has no enrollment for the current academic year."
                )
            if (enrollment.status or "").lower() != EnrollmentStatus.ENROLLED:
                raise EnrollmentLifecycleError(
                    f"Current enrollment status is '{enrollment.status}'. "
                    "Only enrolled students can be transferred out."
                )
        else:
            return False, f"Unknown action '{action}'.", None

        if action == "complete_year":
            normalized = (outcome or "").lower().strip()
            if normalized not in YearEndOutcome.close_year_outcomes():
                return False, "outcome must be promoted or repeated.", None
            if enrollment and normalized == YearEndOutcome.PROMOTED:
                next_grade = resolve_next_grade_level(
                    enrollment.grade_level, normalized
                )
                if next_grade is None:
                    return (
                        False,
                        "No higher grade level configured; use graduate instead.",
                        None,
                    )
                ok, overall_average, avg_reason = meets_minimum_average(
                    student,
                    action=action,
                    outcome=normalized,
                    rules=rules,
                )
                if not ok:
                    return False, avg_reason, overall_average

        if action == "mid_year_promote":
            if enrollment:
                next_grade = resolve_next_grade_level(
                    enrollment.grade_level, YearEndOutcome.PROMOTED
                )
                if next_grade is None:
                    return (
                        False,
                        "No higher grade level configured.",
                        None,
                    )
            ok, overall_average, avg_reason = meets_minimum_average(
                student,
                action=action,
                outcome=YearEndOutcome.PROMOTED,
                rules=rules,
            )
            if not ok:
                return False, avg_reason, overall_average

        if overall_average is None:
            from students.services.promotion_rules import get_student_overall_average

            overall_average = get_student_overall_average(student)

        return True, None, overall_average
    except EnrollmentLifecycleError as exc:
        return False, str(exc), overall_average


def _is_auto_year_end_outcome(outcome: str | None) -> bool:
    if outcome is None:
        return True
    normalized = (outcome or "").lower().strip()
    return normalized in ("", "auto")


def resolve_year_end_projected_outcome(
    student,
    *,
    rules: dict | None = None,
) -> tuple[str | None, float | None, str | None]:
    """
    Determine promoted vs repeated from year_closure_min_overall_average.
    Returns (projected_outcome, overall_average, ineligibility_reason).
    """
    from students.services.enrollment_lifecycle import _require_enrolled_enrollment

    rules = rules or get_promotion_rules()
    enrollment = resolve_current_enrollment(student)

    try:
        _require_enrolled_enrollment(enrollment)
    except EnrollmentLifecycleError as exc:
        return None, None, str(exc)

    minimum = rules.get("year_closure_min_overall_average")
    average = get_student_overall_average(student)

    if minimum is None:
        projected = YearEndOutcome.PROMOTED
    elif average is None:
        return (
            None,
            None,
            f"No overall average available (minimum required: {minimum}%).",
        )
    elif average >= minimum:
        projected = YearEndOutcome.PROMOTED
    else:
        projected = YearEndOutcome.REPEATED

    if projected == YearEndOutcome.PROMOTED:
        next_grade = resolve_next_grade_level(
            enrollment.grade_level, projected
        )
        if next_grade is None:
            return (
                None,
                average,
                "No higher grade level configured; use graduate instead.",
            )

    return projected, average, None


def preview_bulk(
    *,
    action: str,
    selection_mode: str,
    student_ids: list[str] | None = None,
    grade_level: str | None = None,
    section: str | None = None,
    search: str | None = None,
    outcome: str | None = None,
) -> dict[str, Any]:
    if action not in VALID_BULK_ACTIONS:
        raise EnrollmentLifecycleError(
            f"action must be one of: {', '.join(sorted(VALID_BULK_ACTIONS))}."
        )

    _validate_selection_scope(
        selection_mode=selection_mode,
        student_ids=student_ids,
        grade_level=grade_level,
        section=section,
    )

    rules = get_promotion_rules()
    auto_year_end = action == "complete_year" and _is_auto_year_end_outcome(outcome)
    response_outcome = "auto" if auto_year_end else outcome

    qs = build_candidate_queryset(
        student_ids=student_ids if selection_mode == "ids" else None,
        grade_level=grade_level if selection_mode == "filters" else None,
        section=section if selection_mode == "filters" else None,
        search=search if selection_mode == "filters" else None,
    )

    total = qs.count()
    truncated = total > BULK_MAX_STUDENTS
    if truncated:
        qs = qs[:BULK_MAX_STUDENTS]

    rows: list[dict] = []
    eligible_count = 0
    for student in qs:
        grade, sect, enroll_status = _enrollment_snapshot(student)
        projected_outcome = None
        row_outcome = outcome

        if auto_year_end:
            projected_outcome, average, project_reason = (
                resolve_year_end_projected_outcome(student, rules=rules)
            )
            if project_reason:
                ok, reason, overall_average = False, project_reason, average
            else:
                row_outcome = projected_outcome
                ok, reason, overall_average = check_eligibility(
                    student,
                    action,
                    outcome=row_outcome,
                    rules=rules,
                )
        else:
            ok, reason, overall_average = check_eligibility(
                student, action, outcome=row_outcome, rules=rules
            )
            if action == "complete_year" and row_outcome:
                projected_outcome = row_outcome

        if ok:
            eligible_count += 1
        rows.append(
            {
                "id": str(student.id),
                "id_number": student.id_number,
                "full_name": student.get_full_name(),
                "grade_level": grade,
                "section": sect,
                "enrollment_status": enroll_status,
                "overall_average": overall_average,
                "projected_outcome": projected_outcome,
                "eligible": ok,
                "skip_reason": reason,
            }
        )

    return {
        "action": action,
        "outcome": response_outcome,
        "selection_mode": selection_mode,
        "promotion_rules": rules,
        "total_matched": total,
        "truncated": truncated,
        "max_allowed": BULK_MAX_STUDENTS,
        "eligible_count": eligible_count,
        "skipped_count": len(rows) - eligible_count,
        "students": rows,
        "requires_confirm_phrase": CONFIRM_PHRASE,
    }


def apply_bulk(
    *,
    action: str,
    selection_mode: str,
    student_ids: list[str] | None = None,
    grade_level: str | None = None,
    section: str | None = None,
    search: str | None = None,
    outcome: str | None = None,
    expected_eligible_count: int,
    confirm_phrase: str,
    graduation_date: Optional[date] = None,
    transfer_date: Optional[date] = None,
    transfer_reason: str | None = None,
) -> dict[str, Any]:
    if (confirm_phrase or "").strip() != CONFIRM_PHRASE:
        raise EnrollmentLifecycleError(
            f"confirm_phrase must be exactly '{CONFIRM_PHRASE}'."
        )

    _validate_selection_scope(
        selection_mode=selection_mode,
        student_ids=student_ids,
        grade_level=grade_level,
        section=section,
    )

    apply_outcome = outcome
    if action == "complete_year" and _is_auto_year_end_outcome(outcome):
        apply_outcome = "auto"

    preview = preview_bulk(
        action=action,
        selection_mode=selection_mode,
        student_ids=student_ids,
        grade_level=grade_level,
        section=section,
        search=search,
        outcome=apply_outcome,
    )

    if preview["truncated"]:
        raise EnrollmentLifecycleError(
            f"Selection exceeds {BULK_MAX_STUDENTS} students. Narrow filters or use manual selection."
        )

    if preview["eligible_count"] != expected_eligible_count:
        raise EnrollmentLifecycleError(
            "expected_eligible_count does not match current preview. Run preview again."
        )

    if preview["eligible_count"] == 0:
        raise EnrollmentLifecycleError("No eligible students to update.")

    succeeded = []
    failed = []

    from students.models import Student

    eligible_rows = [row for row in preview["students"] if row["eligible"]]
    eligible_ids = [row["id"] for row in eligible_rows]
    outcome_by_id = {
        row["id"]: row.get("projected_outcome") for row in eligible_rows
    }
    students = Student.objects.filter(id__in=eligible_ids)

    for student in students:
        try:
            if action == "complete_year":
                student_outcome = outcome_by_id.get(str(student.id)) or outcome or ""
                if not student_outcome or student_outcome == "auto":
                    raise EnrollmentLifecycleError(
                        "Missing projected outcome; run preview again."
                    )
                close_enrollment_year(student, student_outcome)
            elif action == "graduate":
                graduate_student(student, graduation_date=graduation_date)
            elif action == "transfer_out":
                transfer_out_student(
                    student,
                    transfer_date=transfer_date,
                    reason=transfer_reason,
                )
            elif action == "mid_year_promote":
                mid_year_promote_student(student)
            succeeded.append(
                {
                    "id": str(student.id),
                    "id_number": student.id_number,
                    "full_name": student.get_full_name(),
                }
            )
        except EnrollmentLifecycleError as exc:
            failed.append(
                {
                    "id": str(student.id),
                    "id_number": student.id_number,
                    "full_name": student.get_full_name(),
                    "error": str(exc),
                }
            )

    return {
        "action": action,
        "applied_count": len(succeeded),
        "failed_count": len(failed),
        "succeeded": succeeded,
        "failed": failed,
    }


def build_promoted_queryset(
    *,
    grade_level: str,
    section: str,
):
    """Students with completed year-end promotion in the given class."""
    from students.models import Student

    if not grade_level or not section:
        raise EnrollmentLifecycleError("grade_level and section are required.")

    return (
        Student.objects.filter(
            enrollments__academic_year__current=True,
            enrollments__status=EnrollmentStatus.COMPLETED,
            enrollments__year_end_outcome=YearEndOutcome.PROMOTED,
            enrollments__grade_level_id=grade_level,
            enrollments__section_id=section,
        )
        .select_related()
        .prefetch_related(
            "enrollments__grade_level",
            "enrollments__section",
            "enrollments__next_grade_level",
            "enrollments__academic_year",
        )
        .distinct()
        .order_by("last_name", "first_name", "id_number")
    )


def list_promoted_students(*, grade_level: str, section: str) -> dict[str, Any]:
    qs = build_promoted_queryset(grade_level=grade_level, section=section)
    rows: list[dict] = []
    for student in qs:
        enrollment = resolve_current_enrollment(student)
        next_grade = None
        if enrollment and enrollment.next_grade_level_id:
            next_grade = enrollment.next_grade_level.name
        grade, sect, enroll_status = _enrollment_snapshot(student)
        rows.append(
            {
                "id": str(student.id),
                "id_number": student.id_number,
                "full_name": student.get_full_name(),
                "grade_level": grade,
                "section": sect,
                "enrollment_status": enroll_status,
                "year_end_outcome": (
                    enrollment.year_end_outcome if enrollment else None
                ),
                "next_grade_level": next_grade,
            }
        )
    return {"total": len(rows), "students": rows}


def undo_promotions(*, student_ids: list[str]) -> dict[str, Any]:
    ids = _parse_id_list(student_ids)
    if not ids:
        raise EnrollmentLifecycleError("At least one student_id is required.")

    from students.models import Student

    students = Student.objects.filter(Q(id_number__in=ids) | Q(id__in=ids)).distinct()
    found_ids = {str(s.id) for s in students} | {s.id_number for s in students}
    missing = [i for i in ids if i not in found_ids]
    if missing and students.count() == 0:
        raise EnrollmentLifecycleError("No matching students found.")

    succeeded = []
    failed = []

    for student in students:
        try:
            enrollment = resolve_current_enrollment(student)
            if enrollment is None:
                raise EnrollmentLifecycleError(
                    "Student has no enrollment for the current academic year."
                )
            status = (enrollment.status or "").lower().strip()
            outcome = (enrollment.year_end_outcome or "").lower().strip()
            if status == EnrollmentStatus.COMPLETED and outcome in YearEndOutcome.close_year_outcomes():
                undo_year_end_promotion(student)
            elif status == EnrollmentStatus.ENROLLED:
                undo_mid_year_promotion(student)
            else:
                raise EnrollmentLifecycleError(
                    "No reversible promotion found for this student."
                )
            succeeded.append(
                {
                    "id": str(student.id),
                    "id_number": student.id_number,
                    "full_name": student.get_full_name(),
                }
            )
        except EnrollmentLifecycleError as exc:
            failed.append(
                {
                    "id": str(student.id),
                    "id_number": student.id_number,
                    "full_name": student.get_full_name(),
                    "error": str(exc),
                }
            )

    return {
        "undone_count": len(succeeded),
        "failed_count": len(failed),
        "succeeded": succeeded,
        "failed": failed,
    }

"""Standard year-end wizard workflow; never bypasses lifecycle or grading rules."""
from __future__ import annotations

from collections import Counter, defaultdict

from django.db import transaction
from rest_framework.exceptions import ValidationError

from common.status import EnrollmentStatus, YearEndOutcome
from students.services.enrollment_lifecycle import close_enrollment_year, graduate_student
from students.services.enrollment_lifecycle_bulk import check_eligibility
from students.services.promotion_rules import get_promotion_rules


def _open_enrollments(academic_year, *, grade_level_id=None, section_id=None, allowed_section_ids=None):
    from students.models import Enrollment

    queryset = Enrollment.objects.filter(
            academic_year=academic_year,
            status=EnrollmentStatus.ENROLLED,
        )
    if grade_level_id:
        queryset = queryset.filter(grade_level_id=grade_level_id)
    if section_id:
        queryset = queryset.filter(section_id=section_id)
    if allowed_section_ids is not None:
        queryset = queryset.filter(section_id__in=allowed_section_ids)
    return list(queryset.select_related("student", "grade_level", "section").order_by("grade_level__level", "section__name", "student__last_name"))


def _validate_outcomes(enrollments, outcomes):
    supplied = {str(key): str(value).strip().lower() for key, value in (outcomes or {}).items()}
    expected = {str(enrollment.student_id) for enrollment in enrollments}
    missing = expected - supplied.keys()
    unexpected = supplied.keys() - expected
    valid = set(YearEndOutcome.close_year_outcomes()) | {YearEndOutcome.GRADUATED}
    invalid = {key: value for key, value in supplied.items() if value not in valid}
    if missing or unexpected or invalid:
        raise ValidationError({"outcomes": {"missing_student_ids": sorted(missing), "unexpected_student_ids": sorted(unexpected), "invalid": invalid}})
    return supplied


def build_year_end_wizard_preview(*, academic_year, outcomes=None, grade_level_id=None, section_id=None, allowed_section_ids=None):
    """Load all active-year candidates and validate supplied outcome choices."""
    rules = get_promotion_rules()
    enrollments = _open_enrollments(academic_year, grade_level_id=grade_level_id, section_id=section_id, allowed_section_ids=allowed_section_ids)
    supplied = {str(key): str(value).strip().lower() for key, value in (outcomes or {}).items()}
    rows = []
    for enrollment in enrollments:
        outcome = supplied.get(str(enrollment.student_id))
        eligible = False
        reason = "Year-end outcome is required."
        average = None
        if outcome:
            eligible, reason, average = check_eligibility(
                enrollment.student,
                "graduate" if outcome == YearEndOutcome.GRADUATED else "complete_year",
                outcome=outcome,
                rules=rules,
            )
        rows.append({
            "student_id": str(enrollment.student_id),
            "id_number": enrollment.student.id_number,
            "student_name": enrollment.student.get_full_name(),
            "grade_level": str(enrollment.grade_level),
            "section": str(enrollment.section),
            "enrollment_status": enrollment.status,
            "overall_average": average,
            "outcome": outcome,
            "eligible": eligible,
            "validation_error": reason,
        })
    return _summary(rows, rules)


def _summary(rows, rules):
    outcome_totals = Counter(row["outcome"] for row in rows if row["outcome"])
    grouped = defaultdict(lambda: {"total": 0, "outcomes": Counter(), "invalid": 0})
    for row in rows:
        key = (row["grade_level"], row["section"])
        grouped[key]["total"] += 1
        if row["outcome"]:
            grouped[key]["outcomes"][row["outcome"]] += 1
        if not row["eligible"]:
            grouped[key]["invalid"] += 1
    return {
        "rules": rules,
        "total_students": len(rows),
        "valid_count": sum(row["eligible"] for row in rows),
        "invalid_count": sum(not row["eligible"] for row in rows),
        "outcome_totals": dict(outcome_totals),
        "classes": [
            {"grade_level": grade, "section": section, "total": value["total"], "outcomes": dict(value["outcomes"]), "invalid": value["invalid"]}
            for (grade, section), value in grouped.items()
        ],
        "students": rows,
    }


def apply_year_end_wizard(*, academic_year, outcomes, consent_acknowledged=False, grade_level_id=None, section_id=None, allowed_section_ids=None, actor=None):
    if consent_acknowledged is not True:
        raise ValidationError({"consent_acknowledged": "Acknowledge the final year-end summary before processing."})
    preview = build_year_end_wizard_preview(academic_year=academic_year, outcomes=outcomes, grade_level_id=grade_level_id, section_id=section_id, allowed_section_ids=allowed_section_ids)
    if preview["invalid_count"]:
        raise ValidationError({"detail": "Resolve all year-end validation issues before submission.", "validation": preview})
    enrollments = _open_enrollments(academic_year, grade_level_id=grade_level_id, section_id=section_id, allowed_section_ids=allowed_section_ids)
    resolved = _validate_outcomes(enrollments, outcomes)
    with transaction.atomic():
        for enrollment in enrollments:
            outcome = resolved[str(enrollment.student_id)]
            if outcome == YearEndOutcome.GRADUATED:
                graduate_student(enrollment.student, academic_year=academic_year)
            else:
                close_enrollment_year(enrollment.student, outcome, academic_year=academic_year)
    from grading.gradebook_initializer import initialize_gradebooks_for_academic_year
    from settings.models import GradingSettings

    settings = GradingSettings.objects.first()
    gradebook_initialization = initialize_gradebooks_for_academic_year(
        academic_year=academic_year,
        grading_style=getattr(settings, "grading_style", "multiple_entry"),
        created_by=actor,
        regenerate=False,
    )
    if not gradebook_initialization.get("success"):
        raise ValidationError({
            "detail": "Year-end outcomes were applied, but gradebook initialization failed.",
            "gradebook_initialization": gradebook_initialization,
        })
    preview["gradebook_initialization"] = gradebook_initialization
    return preview
"""
Grading-settings-driven rules for promotion and year-end closure.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from common.status import YearEndOutcome


def get_promotion_rules() -> dict[str, Any]:
    from settings.models import GradingSettings

    settings = GradingSettings.objects.first()
    if not settings:
        return {
            "allow_year_closure": True,
            "year_closure_min_overall_average": None,
            "year_closure_require_approved_grades": True,
            "allow_mid_year_promotion": False,
            "mid_year_promotion_min_overall_average": None,
        }

    return {
        "allow_year_closure": bool(settings.allow_year_closure),
        "year_closure_min_overall_average": _decimal_to_float(
            settings.year_closure_min_overall_average
        ),
        "year_closure_require_approved_grades": bool(
            settings.year_closure_require_approved_grades
        ),
        "allow_mid_year_promotion": bool(settings.allow_mid_year_promotion),
        "mid_year_promotion_min_overall_average": _decimal_to_float(
            settings.mid_year_promotion_min_overall_average
        ),
    }


def _decimal_to_float(value) -> float | None:
    if value is None:
        return None
    return float(value)


def min_average_for_action(action: str, outcome: str | None, rules: dict) -> float | None:
    if action == "mid_year_promote":
        raw = rules.get("mid_year_promotion_min_overall_average")
        if raw is not None:
            return raw
    if action == "complete_year" and (outcome or "").lower() == YearEndOutcome.PROMOTED:
        return rules.get("year_closure_min_overall_average")
    return None


def grade_status_for_average_check(rules: dict) -> str:
    if rules.get("year_closure_require_approved_grades", True):
        return "approved"
    return "any"


def get_student_overall_average(student) -> float | None:
    from grading.utils import calculate_student_overall_average
    from students.models.student import get_current_academic_year

    academic_year = get_current_academic_year()
    if not academic_year:
        return None

    rules = get_promotion_rules()
    status = grade_status_for_average_check(rules)
    data = calculate_student_overall_average(
        student, academic_year, status=status
    )
    final_avg = data.get("final_average")
    if final_avg is None:
        return None
    return float(final_avg)


def meets_minimum_average(
    student,
    *,
    action: str,
    outcome: str | None = None,
    rules: dict | None = None,
) -> tuple[bool, float | None, str | None]:
    rules = rules or get_promotion_rules()
    minimum = min_average_for_action(action, outcome, rules)
    average = get_student_overall_average(student)

    if minimum is None:
        return True, average, None

    if average is None:
        return (
            False,
            None,
            f"No overall average available (minimum required: {minimum}%).",
        )

    if average < minimum:
        return (
            False,
            average,
            f"Overall average {average:.2f}% is below the minimum {minimum:.2f}%.",
        )

    return True, average, None

"""Employee list summary stats for paginated list responses."""

from __future__ import annotations

from django.db.models import Count, QuerySet

from hr.employee_filters import apply_employee_list_filters
from hr.models import Employee

NON_FILTER_QUERY_PARAMS = frozenset(
    {
        "page",
        "page_size",
        "ordering",
        "include_stats",
        "format",
        "export",
    }
)


def employee_list_filters_applied(params) -> bool:
    """Return True when the request includes user-facing list filters."""
    for key, value in params.items():
        if key in NON_FILTER_QUERY_PARAMS:
            continue
        if value is None:
            continue

        normalized = str(value).strip()
        if not normalized:
            continue

        lowered = normalized.lower()
        if key in {"employment_status", "status"} and lowered in {"all", ""}:
            continue
        if key == "payroll_ready" and lowered in {"all", ""}:
            continue
        if key == "gender" and lowered in {"all", ""}:
            continue
        if key == "is_manager":
            # Used internally to populate manager filter options.
            continue
        return True

    return False


def stats_queryset_for_request(params) -> QuerySet:
    """Return the queryset used for list stats (all employees unless filtered)."""
    queryset = Employee.objects.all()
    if employee_list_filters_applied(params):
        queryset = apply_employee_list_filters(queryset, params)
    return queryset


def compute_employee_list_stats(queryset: QuerySet) -> dict:
    """Aggregate employee counts for dashboard cards."""
    total = queryset.count()
    active = queryset.filter(employment_status=Employee.EmploymentStatus.ACTIVE).count()
    teachers = queryset.filter(is_teacher=True).count()
    departments = (
        queryset.filter(department_id__isnull=False)
        .values("department_id")
        .distinct()
        .count()
    )

    return {
        "total": total,
        "active": active,
        "teachers": teachers,
        "non_teaching": max(total - teachers, 0),
        "departments": departments,
    }

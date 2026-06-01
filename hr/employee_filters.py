"""Shared employee list filters for API list and report export."""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q, QuerySet

from hr.models import Employee


def _read_multi_values(params, key: str) -> list[str]:
    raw = params.get(key)
    if raw is None:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def apply_employee_list_filters(queryset: QuerySet, params) -> QuerySet:
    """Apply list-page query params to an employee queryset."""
    search = params.get("search")
    if search:
        queryset = queryset.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(middle_name__icontains=search)
            | Q(email__icontains=search)
            | Q(id_number__icontains=search)
            | Q(job_title__icontains=search)
        )

    department = params.get("department") or params.get("department_id")
    department_values = _read_multi_values({"department": department}, "department") if department else []
    if department_values:
        queryset = queryset.filter(department_id__in=department_values)

    employment_status = params.get("employment_status") or params.get("status")
    if employment_status and str(employment_status).strip().lower() not in {"all", ""}:
        status_values = _read_multi_values({"employment_status": employment_status}, "employment_status")
        if status_values:
            queryset = queryset.filter(employment_status__in=status_values)

    is_teacher_param = params.get("is_teacher")
    if is_teacher_param is not None:
        normalized = str(is_teacher_param).strip().lower()
        if normalized in {"true", "1", "yes"}:
            queryset = queryset.filter(is_teacher=True)
        elif normalized in {"false", "0", "no"}:
            queryset = queryset.filter(is_teacher=False)

    gender_param = params.get("gender")
    gender_values = _read_multi_values({"gender": gender_param}, "gender") if gender_param else []
    if gender_values:
        queryset = queryset.filter(gender__in=gender_values)

    position_param = params.get("position")
    position_values = _read_multi_values({"position": position_param}, "position") if position_param else []
    if position_values:
        queryset = queryset.filter(position_id__in=position_values)

    manager_param = params.get("manager")
    manager_values = _read_multi_values({"manager": manager_param}, "manager") if manager_param else []
    if manager_values:
        queryset = queryset.filter(manager_id__in=manager_values)

    is_manager_param = params.get("is_manager")
    if is_manager_param is not None:
        normalized = str(is_manager_param).strip().lower()
        if normalized in {"true", "1", "yes"}:
            queryset = queryset.filter(
                id__in=Employee.objects.filter(manager__isnull=False).values("manager_id")
            )

    payroll_ready_param = params.get("payroll_ready")
    if payroll_ready_param is not None and str(payroll_ready_param).strip().lower() not in {"all", ""}:
        from django.utils import timezone

        from payroll_v2.models import EmployeeCompensation

        normalized = str(payroll_ready_param).strip().lower()
        today = timezone.now().date()
        active_compensation = EmployeeCompensation.objects.filter(
            employee_id=OuterRef("pk"),
            is_active=True,
            effective_start_date__lte=today,
        ).filter(Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=today))

        if normalized in {"true", "1", "yes"}:
            queryset = queryset.filter(
                pay_schedule__isnull=False,
                employment_status=Employee.EmploymentStatus.ACTIVE,
            ).annotate(_has_compensation=Exists(active_compensation)).filter(_has_compensation=True)
        elif normalized in {"false", "0", "no"}:
            queryset = queryset.filter(
                Q(pay_schedule__isnull=True)
                | ~Q(employment_status=Employee.EmploymentStatus.ACTIVE)
                | ~Exists(active_compensation)
            )

    hire_date_after = params.get("hire_date_after")
    if hire_date_after:
        queryset = queryset.filter(hire_date__gte=hire_date_after)

    hire_date_before = params.get("hire_date_before")
    if hire_date_before:
        queryset = queryset.filter(hire_date__lte=hire_date_before)

    return queryset

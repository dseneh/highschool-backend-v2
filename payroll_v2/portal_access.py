"""Portal vs admin access rules for payroll v2 employee paystubs."""

from __future__ import annotations

from django.db.models import Q

from hr.models import Employee
from authorization.runtime import user_has_permission

from .enums import PayrollStatus

def user_can_manage_payroll_v2(user) -> bool:
    """True for school staff who manage payroll runs (not employee self-service)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user_has_permission(user, "payroll.configure")


def employee_for_portal_user(user) -> Employee | None:
    """Resolve the HR employee record linked to a portal login."""
    if not user or not getattr(user, "is_authenticated", False):
        return None

    id_number = (getattr(user, "id_number", None) or "").strip()
    if not id_number:
        return None

    return (
        Employee.objects.filter(
            Q(user_account_id_number=id_number) | Q(id_number=id_number),
            active=True,
        )
        .only("id", "id_number", "user_account_id_number")
        .first()
    )


def apply_employee_portal_paystub_filters(qs, user):
    """
    Portal employees only see their own paystubs from paid payroll runs.
    Payroll managers keep the full queryset (subject to other filters).
    """
    if user_can_manage_payroll_v2(user):
        return qs

    employee = employee_for_portal_user(user)
    if not employee:
        return qs.none()

    return qs.filter(employee_id=employee.id, payroll__status=PayrollStatus.PAID)

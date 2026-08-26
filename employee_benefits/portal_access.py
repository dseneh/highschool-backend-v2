"""Portal vs admin access rules for employee benefit disbursements."""

from __future__ import annotations

from django.db.models import Q

from hr.models import Employee
from authorization.runtime import user_has_permission

from .enums import BenefitRequestStatus

def user_can_manage_employee_benefits(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user_has_permission(user, "hr.manage")


def employee_for_portal_user(user) -> Employee | None:
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


def apply_employee_portal_benefit_filters(qs, user):
    """Portal employees only see their own paid benefit lines."""
    if user_can_manage_employee_benefits(user):
        return qs

    employee = employee_for_portal_user(user)
    if not employee:
        return qs.none()

    return qs.filter(
        employee_id=employee.id,
        request__status=BenefitRequestStatus.PAID,
    )

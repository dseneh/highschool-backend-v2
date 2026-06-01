"""Portal vs admin access rules for employee benefit disbursements."""

from __future__ import annotations

from django.db.models import Q

from common.status import Roles
from hr.models import Employee
from users.tenant_access import is_global_superadmin

from .enums import BenefitRequestStatus

_BENEFIT_MANAGER_ROLES = {
    Roles.ADMIN,
    Roles.SUPERADMIN,
    Roles.REGISTRAR,
    Roles.DATA_ENTRY,
}


def user_can_manage_employee_benefits(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_global_superadmin(user) or getattr(user, "is_superuser", False):
        return True

    role = (getattr(user, "role", "") or "").strip().lower()
    if role in _BENEFIT_MANAGER_ROLES:
        return True

    if hasattr(user, "has_privilege") and user.has_privilege("CORE_MANAGE"):
        return True

    return False


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

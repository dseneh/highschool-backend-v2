from rest_framework.exceptions import PermissionDenied

from users.tenant_access import is_global_superadmin


def user_can_manage_employee_benefit_assignments(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_global_superadmin(user) or getattr(user, "is_superuser", False):
        return True
    role = (getattr(user, "role", "") or "").strip().lower()
    return role in {"admin", "accountant", "superadmin"}


def require_manage_employee_benefit_assignments(user) -> None:
    if not user_can_manage_employee_benefit_assignments(user):
        raise PermissionDenied("Only finance or admin can manage employee benefit assignments.")

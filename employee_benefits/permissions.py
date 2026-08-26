from rest_framework.exceptions import PermissionDenied

from authorization.runtime import user_has_permission


def user_can_manage_employee_benefit_assignments(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user_has_permission(user, "hr.manage")


def require_manage_employee_benefit_assignments(user) -> None:
    if not user_can_manage_employee_benefit_assignments(user):
        raise PermissionDenied("Only finance or admin can manage employee benefit assignments.")

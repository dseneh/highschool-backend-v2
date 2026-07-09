from rest_framework.permissions import BasePermission

from common.status import Roles
from users.tenant_access import is_global_superadmin


def user_is_platform_superadmin(user) -> bool:
    return is_global_superadmin(user) or bool(getattr(user, "is_superuser", False))


def user_is_tenant_admin(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_global_superadmin(user) or getattr(user, "is_superuser", False):
        return True
    role = str(getattr(user, "role", "") or "").lower()
    return role in {Roles.ADMIN, Roles.SUPERADMIN}


class IsTenantAdmin(BasePermission):
    def has_permission(self, request, view):
        return user_is_tenant_admin(request.user)

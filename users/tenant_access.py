"""
Helpers for global superadmin access across tenant schemas.

Global superadmins (users.User.role == superadmin) are not the same as
tenant-scoped UserTenantPermissions.is_superuser. The latter only applies
after the user has been linked to the current tenant schema.
"""

from __future__ import annotations

from django_tenants.utils import get_public_schema_name, schema_context

from common.status import Roles


def is_global_superadmin(user) -> bool:
    """True when the user is a platform-level superadmin (role on public User)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    role = str(getattr(user, "role", "") or "").strip().lower()
    return role == Roles.SUPERADMIN


def ensure_global_superadmin_tenant_membership(user, tenant) -> bool:
    """
    Ensure a global superadmin has UserTenantPermissions in the tenant schema.

    Returns True when membership was created, False when already present or not applicable.
    """
    if not is_global_superadmin(user) or not tenant:
        return False

    public_schema = get_public_schema_name()
    if getattr(tenant, "schema_name", None) == public_schema:
        return False

    try:
        if user.has_tenant_permissions():
            return False
    except Exception:
        pass

    try:
        tenant.add_user(user, is_superuser=True, is_staff=True)
        return True
    except Exception:
        return False


def user_has_tenant_workspace_access(user, tenant) -> bool:
    """
    True if the user may use API resources in the given tenant workspace.

    Global superadmins are always allowed (and auto-linked when possible).
    Other users need UserTenantPermissions in that tenant schema.
    """
    if not user or not getattr(user, "is_authenticated", False) or not tenant:
        return False

    if is_global_superadmin(user):
        ensure_global_superadmin_tenant_membership(user, tenant)
        return True

    public_schema = get_public_schema_name()
    if getattr(tenant, "schema_name", None) == public_schema:
        try:
            with schema_context(public_schema):
                return user.has_tenant_permissions()
        except Exception:
            return False

    try:
        return user.has_tenant_permissions()
    except Exception:
        return False

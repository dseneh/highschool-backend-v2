"""Workspace access helpers.

Platform superusers, public SharedRoleAssignment authorization, and tenant RBAC
are intentionally distinct. account_scope is descriptive and never bypasses
an actual role assignment.
"""

from __future__ import annotations

from django_tenants.utils import get_public_schema_name, schema_context


def is_global_superadmin(user) -> bool:
    """True when the canonical public User is a platform-level superuser."""
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_platform_superuser", False)
    )


def user_has_platform_workspace_access(user) -> bool:
    """Require an explicit platform grant (or platform-superuser override)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_global_superadmin(user):
        return True

    from users.access_service import has_platform_role

    return has_platform_role(user)


def ensure_global_superadmin_tenant_membership(user, tenant) -> bool:
    """Ensure a platform superadmin has tenant permission plumbing."""
    if not is_global_superadmin(user) or not tenant:
        return False

    public_schema = get_public_schema_name()
    if getattr(tenant, "schema_name", None) == public_schema:
        return False

    try:
        with schema_context(tenant.schema_name):
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
    """Return whether user has authorization for the requested workspace."""
    if not user or not getattr(user, "is_authenticated", False) or not tenant:
        return False

    public_schema = get_public_schema_name()
    schema_name = getattr(tenant, "schema_name", None)

    if schema_name == public_schema:
        return user_has_platform_workspace_access(user)

    if is_global_superadmin(user):
        ensure_global_superadmin_tenant_membership(user, tenant)
        return True

    from authorization.services import get_assigned_role

    try:
        with schema_context(schema_name):
            return user.has_tenant_permissions() and get_assigned_role(user) is not None
    except Exception:
        return False

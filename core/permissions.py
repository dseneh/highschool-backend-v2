"""DRF permissions for tenant runtime access controls."""

from django_tenants.utils import get_public_schema_name
from rest_framework.permissions import BasePermission

from core.tenant_access import evaluate_tenant_api_access


class TenantWorkspaceAccessPermission(BasePermission):
    """
    Shield tenant-scoped API views so data is only served when the active
    workspace restriction and user context allow it.
    """

    message = "Workspace access is restricted."

    def has_permission(self, request, view):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return True

        if getattr(tenant, "schema_name", None) == get_public_schema_name():
            return True

        frontend_path = request.META.get("HTTP_X_APP_PATH", "")
        decision = evaluate_tenant_api_access(
            tenant,
            getattr(request, "user", None),
            frontend_path=frontend_path,
        )

        if decision.allowed:
            return True

        from core.exceptions import TenantAccessDenied

        raise TenantAccessDenied(detail=decision.detail, code=decision.error_code)

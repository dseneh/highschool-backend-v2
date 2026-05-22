"""
JWT authentication that resolves global users from the public schema.

Users live in the public schema (SHARED_APPS). When a tenant X-Tenant header
switches the connection to a school schema, the default JWT lookup can fail or
return incomplete tenant permission state. This class retries authentication
in the public schema, then ensures global superadmins are linked to the tenant.
"""

from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework_simplejwt.authentication import JWTAuthentication

from users.tenant_access import ensure_global_superadmin_tenant_membership


class TenantAwareJWTAuthentication(JWTAuthentication):
    """JWT auth with public-schema user resolution and superadmin tenant linking."""

    def authenticate(self, request):
        try:
            result = super().authenticate(request)
        except Exception:
            result = None

        if not result:
            try:
                with schema_context(get_public_schema_name()):
                    result = super().authenticate(request)
            except Exception:
                result = None

        if not result:
            return None

        user, token = result
        tenant = getattr(request, "tenant", None)
        if tenant:
            ensure_global_superadmin_tenant_membership(user, tenant)
        return user, token

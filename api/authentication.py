"""
JWT authentication that resolves global users from the public schema.

Users live in the public schema (SHARED_APPS). When a tenant X-Tenant header
switches the connection to a school schema, the default JWT lookup can fail or
return incomplete tenant permission state. This class retries authentication
in the public schema, then ensures global superadmins are linked to the tenant.
"""

from django_tenants.utils import get_public_schema_name, schema_context
from django.utils import timezone
from rest_framework import authentication
from rest_framework_simplejwt.authentication import JWTAuthentication

from users.models import TenantSession
from users.sso_utils import hash_value
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
        if hasattr(request, "_request"):
            from authorization.runtime import initialize_request_authorization

            initialize_request_authorization(request, user)
        return user, token


class TenantSessionAuthentication(authentication.BaseAuthentication):
    """Authenticate requests using a server-side tenant session identifier."""

    def authenticate(self, request):
        raw_session_id = request.META.get("HTTP_X_TENANT_SESSION")
        if not raw_session_id:
            return None

        now = timezone.now()
        session_obj = (
            TenantSession.objects.select_related("user", "tenant")
            .filter(
                session_key_hash=hash_value(raw_session_id),
                revoked_at__isnull=True,
                expires_at__gt=now,
            )
            .first()
        )
        if not session_obj:
            return None

        header_tenant = request.META.get("HTTP_X_TENANT") or request.META.get("HTTP_X_WORKSPACE")
        if header_tenant and header_tenant != getattr(session_obj.tenant, "schema_name", ""):
            return None

        from authorization.runtime import initialize_request_authorization

        initialize_request_authorization(request, session_obj.user)
        return session_obj.user, None


class RBACSessionAuthentication(authentication.SessionAuthentication):
    """Django session authentication with a lazy tenant RBAC request facade."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if not result:
            return None
        user, auth = result
        from authorization.runtime import initialize_request_authorization

        initialize_request_authorization(request, user)
        return user, auth

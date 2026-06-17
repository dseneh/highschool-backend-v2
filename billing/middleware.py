from __future__ import annotations

from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

from billing.permissions import user_is_tenant_admin
from billing.services.access import billing_blocks_writes


class BillingAccessMiddleware(MiddlewareMixin):
    """Block mutating API calls when subscription is in grace or expired state."""

    EXEMPT_PREFIXES = (
        "/api/v1/auth/",
        "/api/v1/billing/",
        "/api/v1/tenants/current/",
        "/health",
        "/admin/",
    )

    def process_request(self, request):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None

        path = request.path or ""
        if any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return None

        from django.db import connection
        from core.models import Tenant

        schema = connection.schema_name
        if not schema or schema == "public":
            return None

        tenant = Tenant.objects.filter(schema_name=schema).first()
        if not tenant:
            return None

        user = getattr(request, "user", None)
        is_admin = user_is_tenant_admin(user) if user and user.is_authenticated else False
        if not billing_blocks_writes(tenant, is_tenant_admin=is_admin):
            return None

        return JsonResponse(
            {
                "detail": "Workspace billing requires attention. Changes are temporarily disabled.",
                "error_code": "billing_read_only",
            },
            status=403,
            json_dumps_params={"ensure_ascii": False},
        )

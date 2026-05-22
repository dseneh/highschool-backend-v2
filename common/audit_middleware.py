"""
Custom auditlog middleware that injects the User-Agent string and
GeoIP location into every LogEntry's ``additional_data`` field.

Replaces the stock ``auditlog.middleware.AuditlogMiddleware`` in MIDDLEWARE.
"""

from django.contrib.auth import get_user_model
from auditlog.middleware import AuditlogMiddleware
from api.authentication import TenantAwareJWTAuthentication

from common.audit_utils import extract_device_metadata, get_client_ip
from common.geoip import resolve_location


class AuditlogDeviceMiddleware(AuditlogMiddleware):
    """Extends the default middleware to capture device + location info."""

    def _resolve_jwt_user(self, request):
        """
        Resolve the authenticated user from the JWT bearer token.

        AuditlogMiddleware captures the actor at middleware time via request.user,
        but for JWT-authenticated APIs Django's AuthenticationMiddleware leaves
        request.user as AnonymousUser (DRF resolves JWT at view dispatch, which is
        after the auditlog context is set). This method performs the JWT lookup early
        so the correct actor is stored in the audit log.
        """
        try:
            auth_result = TenantAwareJWTAuthentication().authenticate(request)
        except Exception:
            auth_result = None

        if not auth_result:
            return None
        user, _ = auth_result
        return user

    def __call__(self, request):
        # If the request comes in with a JWT token, request.user is still
        # AnonymousUser at this point (DRF resolves it later). Resolve the JWT
        # user now so the auditlog context captures the correct actor.
        User = get_user_model()
        current_user = getattr(request, "user", None)
        if not (isinstance(current_user, User) and current_user.is_authenticated):
            jwt_user = self._resolve_jwt_user(request)
            if jwt_user:
                request.user = jwt_user
        return super().__call__(request)

    def get_extra_data(self, request):
        context_data = super().get_extra_data(request)
        additional = extract_device_metadata(request)
        ip = get_client_ip(request)
        location = resolve_location(ip)
        if location:
            additional["location"] = location
        context_data["additional_data"] = additional or None
        return context_data

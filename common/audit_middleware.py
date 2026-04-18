"""
Custom auditlog middleware that injects the User-Agent string and
GeoIP location into every LogEntry's ``additional_data`` field.

Replaces the stock ``auditlog.middleware.AuditlogMiddleware`` in MIDDLEWARE.
"""

from auditlog.middleware import AuditlogMiddleware

from common.audit_utils import get_client_ip
from common.geoip import resolve_location


class AuditlogDeviceMiddleware(AuditlogMiddleware):
    """Extends the default middleware to capture device + location info."""

    def get_extra_data(self, request):
        context_data = super().get_extra_data(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        additional = {}
        if user_agent:
            additional["user_agent"] = user_agent
        ip = get_client_ip(request)
        location = resolve_location(ip)
        if location:
            additional["location"] = location
        context_data["additional_data"] = additional or None
        return context_data

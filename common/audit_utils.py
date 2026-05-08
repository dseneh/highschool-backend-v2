"""
Utility functions for manually creating audit log entries.

Used for authentication events (login, password change, etc.) that are
not automatically captured by django-auditlog's model change signals.
"""

import logging

from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)


DEVICE_HEADER_MAPPINGS = {
    "HTTP_X_DEVICE_NAME": "device_name",
    "HTTP_X_DEVICE_MODEL": "device_model",
    "HTTP_X_DEVICE_BRAND": "device_brand",
    "HTTP_X_DEVICE_TYPE": "device_type",
    "HTTP_X_DEVICE_OS": "device_os",
    "HTTP_X_DEVICE_OS_VERSION": "device_os_version",
    "HTTP_X_APP_PLATFORM": "app_platform",
    "HTTP_X_APP_VERSION": "app_version",
    "HTTP_X_CLIENT_NAME": "client_name",
}

CLIENT_HINT_MAPPINGS = {
    "HTTP_SEC_CH_UA_PLATFORM": "device_os",
    "HTTP_SEC_CH_UA_PLATFORM_VERSION": "device_os_version",
    "HTTP_SEC_CH_UA_MODEL": "device_model",
}


def _normalize_header_value(value):
    if value is None:
        return None

    normalized = str(value).strip().strip('"')
    if not normalized or normalized == "?":
        return None

    return normalized


def extract_device_metadata(request):
    """Extract normalized device metadata from request headers.

    Native mobile clients often send a generic User-Agent, so we also accept
    explicit X-Device-* and X-App-* headers from the client.
    """
    if not request:
        return {}

    metadata = {}

    user_agent = _normalize_header_value(request.META.get("HTTP_USER_AGENT", ""))
    if user_agent:
        metadata["user_agent"] = user_agent

    for header_name, field_name in DEVICE_HEADER_MAPPINGS.items():
        value = _normalize_header_value(request.META.get(header_name))
        if value:
            metadata[field_name] = value

    for header_name, field_name in CLIENT_HINT_MAPPINGS.items():
        if field_name in metadata:
            continue

        value = _normalize_header_value(request.META.get(header_name))
        if value:
            metadata[field_name] = value

    mobile_hint = _normalize_header_value(request.META.get("HTTP_SEC_CH_UA_MOBILE"))
    if "device_type" not in metadata and mobile_hint in {"?1", "1"}:
        metadata["device_type"] = "mobile"

    return metadata


def log_tenant_control_change(request, actor, tenant, before, after):
    """Create an audit entry for admin changes to tenant runtime controls."""
    try:
        from core.models import Tenant

        changed = {}
        for key, previous in before.items():
            current = after.get(key)
            if previous != current:
                changed[key] = {
                    "from": previous,
                    "to": current,
                }

        if not changed:
            return

        content_type = ContentType.objects.get_for_model(Tenant)
        remote_addr = get_client_ip(request) if request else ""
        additional = {
            "event_type": "tenant_runtime_controls_updated",
            "tenant_schema": tenant.schema_name,
            "tenant_name": tenant.name,
            "changes": changed,
        }
        additional.update(extract_device_metadata(request))

        LogEntry.objects.create(
            content_type=content_type,
            object_pk=str(tenant.pk),
            object_repr=str(tenant),
            action=LogEntry.Action.UPDATE,
            changes=str(changed),
            actor=actor if actor and hasattr(actor, "pk") else None,
            remote_addr=remote_addr,
            additional_data=additional,
        )
    except Exception as exc:
        logger.error("Failed to create tenant control audit log: %s", exc, exc_info=True)


def get_client_ip(request):
    """Extract client IP address from the request.

    Priority:
    1. X-Real-Client-IP — set explicitly by our Next.js proxy (most trusted)
    2. X-Forwarded-For — standard proxy header (first IP in chain)
    3. REMOTE_ADDR — direct connection IP (fallback)
    """
    # Our own trusted header forwarded from the Next.js server
    real_client_ip = request.META.get("HTTP_X_REAL_CLIENT_IP")
    if real_client_ip:
        return real_client_ip.strip()

    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def log_auth_event(request, user, event_type, details=None):
    """
    Create an audit log entry for an authentication event.

    Auth events (login, logout, password change) are actions, not model
    changes, so they aren't captured by django-auditlog signals. This
    helper writes a LogEntry manually in the current tenant schema.

    Args:
        request: The HTTP request (used for IP address).
        user: The User instance the event relates to (None for failed logins).
        event_type: Short label, e.g. "login_success", "login_failed",
                    "password_changed", "password_reset".
        details: Optional dict with extra context.
    """
    try:
        from users.models import User as UserModel

        content_type = ContentType.objects.get_for_model(UserModel)
        remote_addr = get_client_ip(request) if request else ""

        additional = {"event_type": event_type}
        additional.update(extract_device_metadata(request))

        # Resolve location from IP
        from common.geoip import resolve_location

        location = resolve_location(remote_addr)
        if location:
            additional["location"] = location

        if details:
            additional.update(details)

        LogEntry.objects.create(
            content_type=content_type,
            object_pk=str(user.pk) if user else "",
            object_repr=str(user) if user else "unknown",
            action=LogEntry.Action.ACCESS,
            changes="{}",
            actor=user if user and hasattr(user, "pk") else None,
            remote_addr=remote_addr,
            additional_data=additional,
        )
    except Exception as exc:
        logger.error("Failed to create auth audit log: %s", exc, exc_info=True)

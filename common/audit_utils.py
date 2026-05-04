"""
Utility functions for manually creating audit log entries.

Used for authentication events (login, password change, etc.) that are
not automatically captured by django-auditlog's model change signals.
"""

import logging

from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)


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
        user_agent = request.META.get("HTTP_USER_AGENT", "") if request else ""

        additional = {
            "event_type": "tenant_runtime_controls_updated",
            "tenant_schema": tenant.schema_name,
            "tenant_name": tenant.name,
            "changes": changed,
        }
        if user_agent:
            additional["user_agent"] = user_agent

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

        user_agent = request.META.get("HTTP_USER_AGENT", "") if request else ""

        additional = {"event_type": event_type}
        if user_agent:
            additional["user_agent"] = user_agent

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

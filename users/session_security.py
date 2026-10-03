"""Tracked JWT sessions and suspicious-login detection."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta
from datetime import timezone as datetime_timezone

from django.db import transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from common.audit_utils import extract_device_metadata, get_client_ip
from common.geoip import resolve_location
from users.models import (
    AuthenticationAuditEvent,
    RefreshTokenFamily,
    TenantSession,
)
from users.models import (
    RefreshToken as RefreshTokenRecord,
)
from users.sso_utils import hash_value


def _token_expiry(refresh) -> datetime:
    return datetime.fromtimestamp(int(refresh["exp"]), tz=datetime_timezone.utc)


def _session_metadata(request) -> dict:
    metadata = extract_device_metadata(request)
    location = resolve_location(get_client_ip(request))
    if location:
        metadata["location"] = location
    return metadata


def _safe_ip(request):
    candidate = get_client_ip(request)
    try:
        return str(ipaddress.ip_address(candidate))
    except (TypeError, ValueError):
        return None


def _device_fingerprint(metadata: dict) -> tuple[str, ...]:
    return tuple(
        str(metadata.get(key, "")).strip().lower()
        for key in (
            "device_name",
            "device_model",
            "device_type",
            "device_os",
            "client_name",
            "user_agent",
        )
    )


def _country(metadata: dict) -> str:
    location = metadata.get("location") or {}
    if not isinstance(location, dict):
        return ""
    return (
        str(location.get("country_code") or location.get("country") or "")
        .strip()
        .lower()
    )


def record_security_event(*, request, user, event_type: str, metadata=None):
    tenant = getattr(request, "tenant", None)
    with schema_context(get_public_schema_name()):
        return AuthenticationAuditEvent.objects.create(
            event_type=event_type,
            user=user,
            tenant=tenant
            if getattr(tenant, "schema_name", "") != get_public_schema_name()
            else None,
            ip_address=_safe_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            metadata=metadata or {},
        )


def register_jwt_session(*, user, request, refresh):
    """Attach a revocable server-side session to a newly issued JWT pair."""
    tenant = getattr(request, "tenant", None)
    if tenant is None or getattr(tenant, "schema_name", "") == get_public_schema_name():
        return None

    metadata = _session_metadata(request)
    ip_address = _safe_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    # Resolve role information while the tenant schema is active.
    from authorization.runtime import resolve_authorization_context

    auth_context = resolve_authorization_context(user)
    roles = [str(auth_context.role_id)] if auth_context.role_id else []

    with schema_context(get_public_schema_name()), transaction.atomic():
        prior_sessions = list(
            TenantSession.objects.filter(user=user, revoked_at__isnull=True)
            .exclude(device_metadata={})
            .order_by("-last_used_at")[:10]
        )
        family = RefreshTokenFamily.objects.create(user=user, tenant=tenant)
        session = TenantSession.objects.create(
            session_key_hash=hash_value(str(refresh["jti"])),
            user=user,
            tenant=tenant,
            membership_id="",
            roles=roles,
            permission_version=1,
            refresh_token_family=family,
            expires_at=_token_expiry(refresh),
            ip_address=ip_address,
            user_agent=user_agent,
            device_metadata=metadata,
        )
        refresh["session_id"] = str(session.id)
        refresh_value = str(refresh)
        RefreshTokenRecord.objects.create(
            family=family,
            tenant_session=session,
            token_hash=hash_value(refresh_value),
            expires_at=_token_expiry(refresh),
        )

        new_fingerprint = _device_fingerprint(metadata)
        new_country = _country(metadata)
        known_device = any(
            _device_fingerprint(item.device_metadata) == new_fingerprint
            for item in prior_sessions
        )
        known_country = not new_country or any(
            _country(item.device_metadata) == new_country for item in prior_sessions
        )
        suspicious = bool(
            prior_sessions
            and (
                not known_country
                or (
                    not known_device
                    and ip_address
                    and all(item.ip_address != ip_address for item in prior_sessions)
                )
            )
        )

        AuthenticationAuditEvent.objects.create(
            event_type="suspicious_login" if suspicious else "login_session_created",
            user=user,
            tenant=tenant,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={
                "session_id": str(session.id),
                "device": metadata,
                "suspicious": suspicious,
            },
        )

    if suspicious:
        from common.email_service import send_suspicious_login_email

        send_suspicious_login_email(user, metadata=metadata, ip_address=ip_address)
    return session


def touch_and_validate_session(*, user, session_id) -> bool:
    """Validate a JWT session and periodically advance its activity time."""
    if not session_id:
        return True  # Preserve valid sessions issued before this rollout.
    now = timezone.now()
    with schema_context(get_public_schema_name()):
        session = TenantSession.objects.filter(
            id=session_id,
            user=user,
            revoked_at__isnull=True,
            expires_at__gt=now,
        ).first()
        if session is None:
            return False
        if session.last_used_at < now - timedelta(minutes=5):
            TenantSession.objects.filter(pk=session.pk).update(last_used_at=now)
    return True

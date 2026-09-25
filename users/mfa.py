"""Email MFA policy and challenge lifecycle for privileged sign-ins."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from users.models import EmailMFAChallenge
from users.tenant_access import is_global_superadmin


logger = logging.getLogger(__name__)

DEFAULT_PRIVILEGED_PERMISSIONS = frozenset(
    {
        "finance.transactions.approve",
        "finance.settings.manage",
        "payroll.process",
        "payroll.review",
        "payroll.approve",
        "payroll.configure",
    }
)


def _setting(name, default):
    return getattr(settings, name, default)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mask_email(email: str) -> str:
    local, separator, domain = (email or "").partition("@")
    if not separator:
        return "***"
    visible = local[:1]
    return f"{visible}{'*' * max(3, len(local) - 1)}@{domain}"


def _configured_privileged_permissions() -> set[str]:
    configured = _setting("EMAIL_MFA_PRIVILEGED_PERMISSIONS", DEFAULT_PRIVILEGED_PERMISSIONS)
    if isinstance(configured, str):
        configured = configured.split(",")
    return {str(code).strip() for code in configured if str(code).strip()}


def _is_privileged_in_current_schema(user) -> bool:
    from authorization.models import TenantMembership
    from authorization.runtime import resolve_authorization_context
    from authorization.services import get_applicable_shared_role

    membership = TenantMembership.objects.select_related("role").filter(
        user_id=user.pk, is_active=True
    ).first()
    if membership is None:
        return False
    if membership.role_id and membership.role.is_active and membership.role.system_key == "admin":
        return True
    if membership.shared_role_id:
        try:
            role = get_applicable_shared_role(membership.shared_role_id)
        except Exception:
            role = None
        if role and role.is_active and role.system_key == "admin":
            return True
    context = resolve_authorization_context(user)
    return bool(set(context.permissions).intersection(_configured_privileged_permissions()))


def requires_email_mfa(user) -> bool:
    if not _setting("EMAIL_MFA_PRIVILEGED_ENABLED", False):
        return False
    if is_global_superadmin(user):
        return True

    public_schema = get_public_schema_name()
    current_schema = connection.schema_name
    if current_schema != public_schema:
        return _is_privileged_in_current_schema(user)

    # Central login has no selected workspace. Require MFA if any accessible
    # workspace grants the account privileged authority.
    schemas = user.tenants.filter(active=True).exclude(
        schema_name=public_schema
    ).values_list("schema_name", flat=True)
    for schema_name in schemas:
        try:
            with schema_context(schema_name):
                if _is_privileged_in_current_schema(user):
                    return True
        except Exception:
            # Central sign-in must fail closed: if a tenant grant cannot be
            # inspected, require MFA rather than risk bypassing it.
            logger.exception(
                "Unable to inspect MFA privilege grants in schema %s", schema_name
            )
            return True
    return False


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def issue_challenge(user, tenant_schema: str, *, purpose="login", action="", context=""):
    from common.email_service import send_email_mfa_code

    now = timezone.now()
    ttl = int(_setting("EMAIL_MFA_CODE_TTL_SECONDS", 600))
    raw_token = secrets.token_urlsafe(32)
    code = _new_code()
    public_schema = get_public_schema_name()
    with schema_context(public_schema), transaction.atomic():
        EmailMFAChallenge.objects.select_for_update().filter(
            user=user,
            tenant_schema=tenant_schema,
            purpose=purpose,
            action=action,
            context=context,
            used_at__isnull=True,
            invalidated_at__isnull=True,
        ).update(invalidated_at=now)
        challenge = EmailMFAChallenge.objects.create(
            user=user,
            tenant_schema=tenant_schema,
            purpose=purpose,
            action=action,
            context=context,
            token_hash=token_digest(raw_token),
            code_hash=make_password(code),
            expires_at=now + timedelta(seconds=ttl),
            last_sent_at=now,
        )
        if not send_email_mfa_code(user, code, ttl_seconds=ttl):
            challenge.invalidated_at = now
            challenge.save(update_fields=["invalidated_at", "updated_at"])
            return None
    return challenge, raw_token


def get_challenge_for_update(raw_token: str, tenant_schema: str, *, purpose="login"):
    return EmailMFAChallenge.objects.select_for_update().select_related("user").filter(
        token_hash=token_digest(raw_token), tenant_schema=tenant_schema, purpose=purpose
    ).first()


def challenge_is_usable(challenge) -> bool:
    return bool(
        challenge
        and challenge.used_at is None
        and challenge.invalidated_at is None
        and challenge.expires_at > timezone.now()
    )


def verify_code(challenge, code: str) -> bool:
    maximum = int(_setting("EMAIL_MFA_MAX_ATTEMPTS", 5))
    if not challenge_is_usable(challenge) or challenge.failed_attempts >= maximum:
        return False
    if not check_password(str(code), challenge.code_hash):
        challenge.failed_attempts += 1
        fields = ["failed_attempts", "updated_at"]
        if challenge.failed_attempts >= maximum:
            challenge.invalidated_at = timezone.now()
            fields.append("invalidated_at")
        challenge.save(update_fields=fields)
        return False
    challenge.used_at = timezone.now()
    challenge.save(update_fields=["used_at", "updated_at"])
    return True


def resend_code(challenge) -> bool:
    from common.email_service import send_email_mfa_code

    if not challenge_is_usable(challenge):
        return False
    now = timezone.now()
    cooldown = int(_setting("EMAIL_MFA_RESEND_COOLDOWN_SECONDS", 60))
    maximum = int(_setting("EMAIL_MFA_MAX_RESENDS", 5))
    if challenge.resend_count >= maximum or challenge.last_sent_at + timedelta(seconds=cooldown) > now:
        return False
    code = _new_code()
    ttl = int(_setting("EMAIL_MFA_CODE_TTL_SECONDS", 600))
    if not send_email_mfa_code(challenge.user, code, ttl_seconds=ttl):
        return False
    challenge.code_hash = make_password(code)
    challenge.failed_attempts = 0
    challenge.resend_count += 1
    challenge.last_sent_at = now
    challenge.expires_at = now + timedelta(seconds=ttl)
    challenge.save(update_fields=[
        "code_hash", "failed_attempts", "resend_count", "last_sent_at", "expires_at", "updated_at"
    ])
    return True

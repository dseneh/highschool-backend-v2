"""Verified email-change recovery for privileged accounts."""

import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from users.mfa import token_digest
from users.models import EmailMFARecovery


def issue_recovery(*, user, initiated_by, tenant_schema: str, new_email: str):
    from common.email_service import send_email_mfa_recovery_code

    now = timezone.now()
    raw_token = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    with transaction.atomic():
        EmailMFARecovery.objects.select_for_update().filter(
            user=user,
            used_at__isnull=True,
            invalidated_at__isnull=True,
        ).update(invalidated_at=now)
        recovery = EmailMFARecovery.objects.create(
            user=user,
            initiated_by=initiated_by,
            tenant_schema=tenant_schema,
            new_email=new_email,
            token_hash=token_digest(raw_token),
            code_hash=make_password(code),
            expires_at=now + timedelta(minutes=15),
        )
        if not send_email_mfa_recovery_code(
            email=new_email,
            user=user,
            code=code,
            ttl_minutes=15,
        ):
            recovery.invalidated_at = now
            recovery.save(update_fields=["invalidated_at", "updated_at"])
            return None
    return recovery, raw_token


def verify_recovery(*, raw_token: str, code: str):
    now = timezone.now()
    recovery = (
        EmailMFARecovery.objects.select_for_update()
        .select_related("user", "initiated_by")
        .filter(token_hash=token_digest(raw_token))
        .first()
    )
    if (
        recovery is None
        or recovery.used_at is not None
        or recovery.invalidated_at is not None
        or recovery.expires_at <= now
        or recovery.failed_attempts >= 5
    ):
        return None
    if not check_password(code, recovery.code_hash):
        recovery.failed_attempts += 1
        if recovery.failed_attempts >= 5:
            recovery.invalidated_at = now
        recovery.save(update_fields=["failed_attempts", "invalidated_at", "updated_at"])
        return None
    recovery.used_at = now
    recovery.save(update_fields=["used_at", "updated_at"])
    return recovery

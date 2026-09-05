import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from .models import ApplicantAccessToken, ApplicantIdentity


VERIFICATION_PURPOSE = "email_verification"
SESSION_PURPOSE = "portal_session"
MAX_VERIFICATION_ATTEMPTS = 5


def hash_session_token(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_email_verification(*, application, lifetime_minutes=15):
    ApplicantAccessToken.objects.filter(
        application=application,
        purpose=VERIFICATION_PURPOSE,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
    code = f"{secrets.randbelow(1_000_000):06d}"
    token = ApplicantAccessToken.objects.create(
        application=application,
        purpose=VERIFICATION_PURPOSE,
        token_hash=make_password(code),
        expires_at=timezone.now() + timedelta(minutes=lifetime_minutes),
    )
    return token, code


def issue_portal_session(*, application, lifetime_hours=24):
    raw_token = secrets.token_urlsafe(32)
    token = ApplicantAccessToken.objects.create(
        application=application,
        purpose=SESSION_PURPOSE,
        token_hash=hash_session_token(raw_token),
        expires_at=timezone.now() + timedelta(hours=lifetime_hours),
    )
    return token, raw_token


@transaction.atomic
def verify_email_code(*, code, challenge_id=None, request_id=None):
    now = timezone.now()
    filters = {"pk": challenge_id} if challenge_id else {"application__request_id": request_id}
    token = ApplicantAccessToken.objects.select_for_update().select_related("application").filter(
        purpose=VERIFICATION_PURPOSE,
        active=True,
        used_at__isnull=True,
        revoked_at__isnull=True,
        **filters,
    ).order_by("-created_at").first()
    if token is None or token.expires_at <= now:
        raise ValueError("The verification code is invalid or expired.")
    if token.attempts >= MAX_VERIFICATION_ATTEMPTS:
        raise ValueError("The verification code is invalid or expired.")
    if not check_password(code, token.token_hash):
        token.attempts += 1
        token.save(update_fields=["attempts", "updated_at"])
        raise ValueError("The verification code is invalid or expired.")

    token.used_at = now
    token.save(update_fields=["used_at", "updated_at"])
    identity, _created = ApplicantIdentity.objects.select_for_update().get_or_create(
        application=token.application
    )
    identity.email_verified_at = now
    identity.failed_attempts = 0
    identity.locked_until = None
    identity.save(update_fields=["email_verified_at", "failed_attempts", "locked_until", "updated_at"])
    return token.application

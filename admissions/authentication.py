from dataclasses import dataclass

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from .models import ApplicantAccessToken
from .security import SESSION_PURPOSE, hash_session_token


@dataclass(frozen=True)
class ApplicantPrincipal:
    application: object

    @property
    def is_authenticated(self):
        return True


class ApplicantSessionAuthentication(BaseAuthentication):
    keyword = b"applicant"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if len(parts) != 2 or parts[0].lower() != self.keyword:
            raise AuthenticationFailed("Invalid applicant authorization header.")
        try:
            raw_token = parts[1].decode("utf-8")
        except UnicodeError as exc:
            raise AuthenticationFailed("Invalid applicant authorization header.") from exc
        now = timezone.now()
        token = ApplicantAccessToken.objects.select_related("application").filter(
            token_hash=hash_session_token(raw_token),
            purpose=SESSION_PURPOSE,
            active=True,
            revoked_at__isnull=True,
            expires_at__gt=now,
        ).first()
        if token is None:
            raise AuthenticationFailed("Applicant session is invalid or expired.")
        ApplicantAccessToken.objects.filter(pk=token.pk).update(last_used_at=now)
        return ApplicantPrincipal(application=token.application), token

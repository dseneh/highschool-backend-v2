"""User security endpoints: MFA and global session revocation."""

from django.core import signing
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.mfa import (
    decrypt_secret,
    encrypt_secret,
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    provisioning_uri,
    verify_totp,
)
from users.models import CentralAuthSession, RefreshTokenFamily, TenantSession, User
from users.security_auth import (
    MFA_CHALLENGE_MAX_AGE_SECONDS,
    MFA_CHALLENGE_SALT,
    SecurityTokenObtainPairSerializer,
)
from users.serializers import UserSerializer


def _is_privileged(request) -> bool:
    user = request.user
    if bool(getattr(user, "is_platform_superuser", False)):
        return True
    return bool(getattr(request, "can", lambda permission: False)("tenant.settings.manage"))


def _revoke_server_sessions(user_id, *, reason_time=None):
    now = reason_time or timezone.now()
    CentralAuthSession.objects.filter(user_id=user_id, revoked_at__isnull=True).update(revoked_at=now)
    TenantSession.objects.filter(user_id=user_id, revoked_at__isnull=True).update(revoked_at=now)
    RefreshTokenFamily.objects.filter(user_id=user_id, revoked_at__isnull=True).update(revoked_at=now)


class SecurityStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        privileged = _is_privileged(request)
        with schema_context(get_public_schema_name()):
            user = User.objects.get(pk=request.user.pk)
            return Response(
                {
                    "mfa_enabled": user.mfa_enabled,
                    "mfa_required": user.mfa_required,
                    "mfa_confirmed_at": user.mfa_confirmed_at,
                    "privileged": privileged,
                    "security_version": user.security_version,
                }
            )


class MFASetupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        with schema_context(get_public_schema_name()):
            user = User.objects.get(pk=request.user.pk)
            secret = generate_secret()
            user.mfa_secret_envelope = encrypt_secret(secret, user.id)
            user.mfa_enabled = False
            user.mfa_confirmed_at = None
            user.mfa_recovery_code_hashes = []
            user.save(
                update_fields=[
                    "mfa_secret_envelope",
                    "mfa_enabled",
                    "mfa_confirmed_at",
                    "mfa_recovery_code_hashes",
                ]
            )
            return Response(
                {
                    "secret": secret,
                    "provisioning_uri": provisioning_uri(secret, user.email or user.username or user.id_number),
                    "issuer": "EzySchool",
                }
            )


class MFAConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        code = str(request.data.get("code") or "")
        privileged = _is_privileged(request)
        now = timezone.now()
        with schema_context(get_public_schema_name()):
            user = User.objects.get(pk=request.user.pk)
            if not user.mfa_secret_envelope:
                return Response({"detail": "Start MFA setup first."}, status=status.HTTP_400_BAD_REQUEST)
            secret = decrypt_secret(user.mfa_secret_envelope, user.id)
            if not verify_totp(secret, code):
                return Response({"detail": "Invalid verification code."}, status=status.HTTP_400_BAD_REQUEST)

            recovery_codes, hashes = generate_recovery_codes()
            user.mfa_enabled = True
            user.mfa_required = bool(user.mfa_required or privileged)
            user.mfa_confirmed_at = now
            user.mfa_recovery_code_hashes = hashes
            user.security_version = F("security_version") + 1
            user.save(
                update_fields=[
                    "mfa_enabled",
                    "mfa_required",
                    "mfa_confirmed_at",
                    "mfa_recovery_code_hashes",
                    "security_version",
                ]
            )
            _revoke_server_sessions(user.id, reason_time=now)
            return Response(
                {
                    "detail": "Multi-factor authentication enabled. Existing sessions were invalidated; sign in again using MFA.",
                    "recovery_codes": recovery_codes,
                    "warning": "Store these recovery codes securely. They are shown only once.",
                }
            )


class MFADisableView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        code = str(request.data.get("code") or "")
        now = timezone.now()
        with schema_context(get_public_schema_name()):
            user = User.objects.get(pk=request.user.pk)
            if not user.mfa_enabled or not user.mfa_secret_envelope:
                return Response({"detail": "MFA is not enabled."}, status=status.HTTP_400_BAD_REQUEST)
            secret = decrypt_secret(user.mfa_secret_envelope, user.id)
            if not verify_totp(secret, code):
                return Response({"detail": "Invalid verification code."}, status=status.HTTP_400_BAD_REQUEST)
            if user.mfa_required:
                return Response(
                    {"detail": "MFA is required for this privileged account. Remove the requirement before disabling it."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            user.mfa_enabled = False
            user.mfa_secret_envelope = None
            user.mfa_confirmed_at = None
            user.mfa_recovery_code_hashes = []
            user.security_version = F("security_version") + 1
            user.save(update_fields=["mfa_enabled", "mfa_secret_envelope", "mfa_confirmed_at", "mfa_recovery_code_hashes", "security_version"])
            _revoke_server_sessions(user.id, reason_time=now)
            return Response({"detail": "MFA disabled. Existing sessions were invalidated."})


class MFAChallengeVerifyView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        challenge = str(request.data.get("challenge") or "")
        code = str(request.data.get("code") or "")
        try:
            payload = signing.loads(
                challenge,
                salt=MFA_CHALLENGE_SALT,
                max_age=MFA_CHALLENGE_MAX_AGE_SECONDS,
            )
        except signing.BadSignature:
            return Response({"detail": "MFA challenge is invalid or expired."}, status=status.HTTP_400_BAD_REQUEST)

        with schema_context(get_public_schema_name()):
            user = User.objects.filter(pk=payload.get("user_id"), is_active=True).first()
            if not user or not user.mfa_enabled or not user.mfa_secret_envelope:
                return Response({"detail": "MFA challenge is no longer valid."}, status=status.HTTP_400_BAD_REQUEST)
            if int(payload.get("security_version", 0)) != int(user.security_version):
                return Response({"detail": "Session state changed. Sign in again."}, status=status.HTTP_401_UNAUTHORIZED)

            secret = decrypt_secret(user.mfa_secret_envelope, user.id)
            valid = verify_totp(secret, code)
            if not valid and code:
                recovery_hash = hash_recovery_code(code)
                if recovery_hash in user.mfa_recovery_code_hashes:
                    valid = True
                    hashes = list(user.mfa_recovery_code_hashes)
                    hashes.remove(recovery_hash)
                    user.mfa_recovery_code_hashes = hashes
                    user.save(update_fields=["mfa_recovery_code_hashes"])
            if not valid:
                return Response({"detail": "Invalid MFA code."}, status=status.HTTP_400_BAD_REQUEST)

            refresh = SecurityTokenObtainPairSerializer.get_token(user)
            return Response(
                {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                    "user": UserSerializer(user, context={"request": request}).data,
                }
            )


class RevokeAllSessionsView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        now = timezone.now()
        with schema_context(get_public_schema_name()):
            User.objects.filter(pk=request.user.pk).update(security_version=F("security_version") + 1)
            _revoke_server_sessions(request.user.pk, reason_time=now)
        return Response({"detail": "All sessions have been revoked. Sign in again on each device."})

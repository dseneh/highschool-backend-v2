"""Security-aware JWT login, email MFA, and refresh views."""

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.views import TokenRefreshView

from users.models import User
from users.serializers import MultiFieldTokenObtainPairSerializer, UserSerializer
from users.views import MultiFieldTokenObtainPairView


class SecurityTokenObtainPairSerializer(MultiFieldTokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["security_version"] = int(getattr(user, "security_version", 1))
        return token


class SecurityTokenObtainPairView(MultiFieldTokenObtainPairView):
    """Issue JWTs, withholding them until privileged email MFA completes."""

    serializer_class = SecurityTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        from authorization.services import has_assigned_role
        from common.audit_utils import log_auth_event
        from users.mfa import issue_challenge, mask_email, requires_email_mfa

        identifier = request.data.get("username", "")
        password = request.data.get("password", "")
        user = authenticate(request=request, username=identifier, password=password)
        if not user or not user.is_active or not has_assigned_role(user):
            return super().post(request, *args, **kwargs)

        denied = self._enforce_login_policy(request, user, identifier)
        if denied is not None:
            return denied
        if not requires_email_mfa(user):
            return super().post(request, *args, **kwargs)
        if not user.email:
            log_auth_event(request, user, "mfa_delivery_failed", details={"reason": "missing_email"})
            return Response(
                {"detail": "A verified email address is required for privileged sign-in.", "error_code": "MFA_EMAIL_UNAVAILABLE"},
                status=status.HTTP_403_FORBIDDEN,
            )

        tenant_schema = connection.schema_name
        issued = issue_challenge(user, tenant_schema)
        if issued is None:
            log_auth_event(request, user, "mfa_delivery_failed")
            return Response(
                {"detail": "Unable to send a verification code. Please try again.", "error_code": "MFA_DELIVERY_FAILED"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        _challenge, raw_token = issued
        log_auth_event(request, user, "mfa_challenge_issued", details={"tenant_schema": tenant_schema})
        return Response(
            {
                "mfa_required": True,
                "challenge_token": raw_token,
                "expires_in": int(settings.EMAIL_MFA_CODE_TTL_SECONDS),
                "delivery": {"method": "email", "destination": mask_email(user.email)},
            },
            status=status.HTTP_202_ACCEPTED,
        )


class EmailMFAVerifyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from authorization.services import has_assigned_role
        from common.audit_utils import log_auth_event
        from users.mfa import get_challenge_for_update, requires_email_mfa, verify_code

        raw_token = str(request.data.get("challenge_token", ""))
        code = str(request.data.get("code", ""))
        if not raw_token or len(raw_token) > 256 or len(code) != 6 or not code.isdigit():
            return Response({"detail": "Invalid or expired verification code."}, status=status.HTTP_400_BAD_REQUEST)

        tenant_schema = connection.schema_name
        with schema_context(get_public_schema_name()), transaction.atomic():
            challenge = get_challenge_for_update(raw_token, tenant_schema)
            if not verify_code(challenge, code):
                user = challenge.user if challenge else None
                log_auth_event(request, user, "mfa_verification_failed", details={"tenant_schema": tenant_schema})
                return Response({"detail": "Invalid or expired verification code."}, status=status.HTTP_400_BAD_REQUEST)
            user = challenge.user

        if not user.is_active or not has_assigned_role(user) or not requires_email_mfa(user):
            log_auth_event(request, user, "mfa_verification_failed", details={"reason": "authorization_changed"})
            return Response({"detail": "Unable to complete sign-in."}, status=status.HTTP_403_FORBIDDEN)
        denied = SecurityTokenObtainPairView()._enforce_login_policy(request, user, user.username or user.email)
        if denied is not None:
            return denied

        refresh = SecurityTokenObtainPairSerializer.get_token(user)
        if settings.SIMPLE_JWT.get("UPDATE_LAST_LOGIN", False):
            user.last_login = timezone.now()
            user.save(update_fields=["last_login"])
        log_auth_event(request, user, "mfa_verification_success", details={"tenant_schema": tenant_schema})
        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": UserSerializer(user, context={"request": request}).data,
            }
        )


class EmailMFAResendView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from common.audit_utils import log_auth_event
        from users.mfa import get_challenge_for_update, resend_code

        raw_token = str(request.data.get("challenge_token", ""))
        if not raw_token or len(raw_token) > 256:
            return Response({"detail": "Unable to resend verification code."}, status=status.HTTP_400_BAD_REQUEST)
        tenant_schema = connection.schema_name
        with schema_context(get_public_schema_name()), transaction.atomic():
            challenge = get_challenge_for_update(raw_token, tenant_schema)
            if not challenge or not resend_code(challenge):
                return Response({"detail": "Unable to resend verification code. Please wait and try again."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            user = challenge.user
        log_auth_event(request, user, "mfa_code_resent", details={"tenant_schema": tenant_schema})
        return Response({"detail": "A new verification code was sent."})


class SecurityTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken(attrs["refresh"])
        user_id = refresh.get("user_id")
        token_version = int(refresh.get("security_version", 1))

        with schema_context(get_public_schema_name()):
            user = User.objects.filter(pk=user_id, is_active=True).first()
            if not user:
                raise serializers.ValidationError({"detail": "Account is no longer active."})
            if token_version != int(user.security_version):
                raise serializers.ValidationError({"detail": "Session has been revoked. Please sign in again."})

        return super().validate(attrs)


class SecurityTokenRefreshView(TokenRefreshView):
    serializer_class = SecurityTokenRefreshSerializer

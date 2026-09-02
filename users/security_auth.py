"""Security-aware JWT login and refresh views."""

from django.core import signing
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.views import TokenRefreshView

from users.models import User
from users.serializers import MultiFieldTokenObtainPairSerializer
from users.views import MultiFieldTokenObtainPairView


MFA_CHALLENGE_SALT = "ezyschool.mfa.login.v1"
MFA_CHALLENGE_MAX_AGE_SECONDS = 300


class SecurityTokenObtainPairSerializer(MultiFieldTokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["security_version"] = int(getattr(user, "security_version", 1))
        return token


class SecurityTokenObtainPairView(MultiFieldTokenObtainPairView):
    serializer_class = SecurityTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code >= 400:
            return response

        user_id = (response.data.get("user") or {}).get("id")
        if not user_id:
            return response

        with schema_context(get_public_schema_name()):
            user = User.objects.filter(pk=user_id).first()
            if not user or not user.mfa_enabled:
                return response

            challenge = signing.dumps(
                {
                    "user_id": str(user.id),
                    "security_version": int(user.security_version),
                    "workspace": request.META.get("HTTP_X_TENANT") or request.META.get("HTTP_X_WORKSPACE") or "",
                },
                salt=MFA_CHALLENGE_SALT,
                compress=True,
            )

        # Password was valid, but no bearer credentials leave the server until
        # the second factor is verified.
        return Response(
            {
                "detail": "Multi-factor authentication is required.",
                "error_code": "MFA_REQUIRED",
                "mfa_required": True,
                "challenge": challenge,
                "expires_in": MFA_CHALLENGE_MAX_AGE_SECONDS,
            },
            status=status.HTTP_202_ACCEPTED,
        )


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

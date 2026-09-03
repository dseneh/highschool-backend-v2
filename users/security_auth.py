"""Security-aware JWT login and refresh views."""

from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.views import TokenRefreshView

from users.models import User
from users.serializers import MultiFieldTokenObtainPairSerializer
from users.views import MultiFieldTokenObtainPairView


class SecurityTokenObtainPairSerializer(MultiFieldTokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["security_version"] = int(getattr(user, "security_version", 1))
        return token


class SecurityTokenObtainPairView(MultiFieldTokenObtainPairView):
    """Issue JWTs containing the current global security version."""

    serializer_class = SecurityTokenObtainPairSerializer


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

"""Tenant security policy endpoints."""

from rest_framework.response import Response
from rest_framework.views import APIView

from settings.access_policies import SettingsAccessPolicy
from settings.models import SecuritySettings
from settings.serializers import SecuritySettingsSerializer
from users.step_up import enforce_step_up


class SecuritySettingsView(APIView):
    permission_classes = [SettingsAccessPolicy]

    def get(self, request):
        policy, _ = SecuritySettings.objects.get_or_create(
            defaults={"created_by": request.user, "updated_by": request.user}
        )
        return Response(SecuritySettingsSerializer(policy).data)

    def patch(self, request):
        policy, _ = SecuritySettings.objects.get_or_create(
            defaults={"created_by": request.user, "updated_by": request.user}
        )
        # Once enabled, changing the security policy itself requires a fresh
        # step-up proof. Enabling it for the first time remains possible.
        enforce_step_up(
            request,
            action="security_settings",
            required=policy.require_mfa_for_security_settings,
        )
        serializer = SecuritySettingsSerializer(policy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        policy = serializer.save(updated_by=request.user)
        return Response(SecuritySettingsSerializer(policy).data)

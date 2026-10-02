from django.db import connection
from django_tenants.utils import schema_context, get_public_schema_name
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from common.permissions import IsSuperAdmin
from core.models import PlatformAuthAppearance

# These layouts work without school-specific imagery or copy.
PLATFORM_AUTH_LAYOUTS = ("classic", "centered", "minimal", "ambient", "aurora", "orbit", "editorial", "studio", "dusk", "water", "boxes", "particles")
AUTH_BACKGROUNDS = ("default", "water", "boxes", "particles")


class PlatformAuthAppearanceSerializer(serializers.ModelSerializer):
    default_layout = serializers.ChoiceField(choices=PLATFORM_AUTH_LAYOUTS)
    workspace_layout = serializers.ChoiceField(choices=("", *PLATFORM_AUTH_LAYOUTS), required=False)
    parent_layout = serializers.ChoiceField(choices=("", *PLATFORM_AUTH_LAYOUTS), required=False)
    background_settings = serializers.JSONField(required=False)

    def validate_background_settings(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Background settings must be an object.")
        for layout, settings in value.items():
            if layout not in PLATFORM_AUTH_LAYOUTS or not isinstance(settings, dict):
                raise serializers.ValidationError("Invalid layout background settings.")
            if set(settings) != {"background", "blur"}:
                raise serializers.ValidationError("Each layout needs a background and blur level.")
            if settings["background"] not in AUTH_BACKGROUNDS:
                raise serializers.ValidationError("Unsupported authentication background.")
            blur = settings["blur"]
            if isinstance(blur, bool) or not isinstance(blur, int) or not 0 <= blur <= 16:
                raise serializers.ValidationError("Blur must be between 0 and 16 pixels.")
        return value

    class Meta:
        model = PlatformAuthAppearance
        fields = ("default_layout", "workspace_layout", "parent_layout", "background_settings")


class PublicAuthAppearanceView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        with schema_context(get_public_schema_name()):
            config = PlatformAuthAppearance.objects.filter(pk=1).first() or PlatformAuthAppearance()
            return Response(PlatformAuthAppearanceSerializer(config).data)


class AdminWorkspaceAppearancePermission(IsSuperAdmin):
    message = "Open the admin platform with your platform administrator role to manage authentication appearance."

    def has_permission(self, request, view):
        workspace = (request.META.get("HTTP_X_TENANT") or request.META.get("HTTP_X_WORKSPACE") or "").strip().lower()
        schema = getattr(getattr(request, "tenant", None), "schema_name", connection.schema_name)
        return (
            super().has_permission(request, view)
            and schema == get_public_schema_name()
            and workspace in ("", "admin", "public")
            and request.META.get("HTTP_X_PARENT_WORKSPACE") != "1"
        )


class PlatformAuthAppearanceView(APIView):
    permission_classes = [AdminWorkspaceAppearancePermission]

    def get(self, request):
        with schema_context(get_public_schema_name()):
            config = PlatformAuthAppearance.objects.filter(pk=1).first() or PlatformAuthAppearance()
            return Response(PlatformAuthAppearanceSerializer(config).data)

    def patch(self, request):
        with schema_context(get_public_schema_name()):
            config = PlatformAuthAppearance.objects.filter(pk=1).first() or PlatformAuthAppearance()
            serializer = PlatformAuthAppearanceSerializer(config, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            # Update only supplied fields, so independent editors do not overwrite overrides.
            PlatformAuthAppearance.objects.update_or_create(pk=1, defaults=serializer.validated_data)
            return Response(PlatformAuthAppearanceSerializer(PlatformAuthAppearance.objects.get(pk=1)).data)

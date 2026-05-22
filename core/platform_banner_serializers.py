"""Serializers for the public-schema :class:`PlatformBanner` model."""

from rest_framework import serializers

from core.models import PlatformBanner


class PlatformBannerSerializer(serializers.ModelSerializer):
    """Full representation used by the admin portal."""

    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PlatformBanner
        fields = [
            "id",
            "title",
            "body",
            "action_url",
            "variant",
            "dismissible",
            "starts_at",
            "ends_at",
            "target_tenants",
            "target_roles",
            "active",
            "created_at",
            "updated_at",
            "created_by_name",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by_name",
        ]

    def get_created_by_name(self, obj):
        user = getattr(obj, "created_by", None)
        if not user:
            return None
        try:
            return user.get_full_name() or user.username
        except Exception:
            return None


class PlatformBannerPublicSerializer(serializers.ModelSerializer):
    """Compact representation served to end users by the banner host."""

    class Meta:
        model = PlatformBanner
        fields = [
            "id",
            "title",
            "body",
            "action_url",
            "variant",
            "dismissible",
            "starts_at",
            "ends_at",
        ]
        read_only_fields = fields

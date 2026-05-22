from rest_framework import serializers

from notifications.models import (
    Notification,
    NotificationCampaign,
    NotificationRule,
    TenantNotificationSettings,
    UserNotificationPreference,
)


class NotificationSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="campaign.title", read_only=True)
    body = serializers.CharField(source="campaign.body", read_only=True)
    category = serializers.CharField(source="campaign.category", read_only=True)
    source = serializers.CharField(source="campaign.source", read_only=True)
    sent_at = serializers.DateTimeField(source="campaign.sent_at", read_only=True)
    campaign_id = serializers.UUIDField(source="campaign.id", read_only=True)
    is_read = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "campaign_id",
            "title",
            "body",
            "category",
            "source",
            "sent_at",
            "read_at",
            "is_read",
            "can_delete",
            "action_url",
            "created_at",
        ]
        read_only_fields = fields

    def get_is_read(self, obj):
        return obj.read_at is not None

    def get_can_delete(self, obj):
        """An admin (or anyone with NOTIFICATION_MANAGE) can delete the
        underlying campaign, which clears it from every recipient's inbox."""
        request = self.context.get("request") if hasattr(self, "context") else None
        user = getattr(request, "user", None) if request else None
        if not user or not getattr(user, "is_authenticated", False):
            return False
        role = (getattr(user, "role", "") or "").lower()
        if role == "admin":
            return True
        try:
            return bool(user.has_privilege("NOTIFICATION_MANAGE"))
        except Exception:
            return False


class NotificationMarkReadSerializer(serializers.Serializer):
    read = serializers.BooleanField(default=True)


class NotificationCampaignSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    delivery_stats = serializers.SerializerMethodField()

    class Meta:
        model = NotificationCampaign
        fields = [
            "id",
            "title",
            "body",
            "category",
            "channels",
            "audience",
            "source",
            "status",
            "scheduled_at",
            "sent_at",
            "recipient_count",
            "is_pinned",
            "deliver_banner",
            "banner_variant",
            "banner_dismissible",
            "banner_starts_at",
            "banner_ends_at",
            "created_at",
            "created_by_name",
            "delivery_stats",
        ]
        read_only_fields = [
            "id",
            "source",
            "status",
            "sent_at",
            "recipient_count",
            "created_at",
            "created_by_name",
            "delivery_stats",
        ]

    def get_created_by_name(self, obj):
        if not obj.created_by_id:
            return None
        user = obj.created_by
        if not user:
            return None
        return user.get_full_name() or user.username

    def get_delivery_stats(self, obj):
        from notifications.models import NotificationDelivery

        qs = NotificationDelivery.objects.filter(campaign=obj)
        return {
            "email_sent": qs.filter(status=NotificationDelivery.Status.SENT).count(),
            "email_failed": qs.filter(status=NotificationDelivery.Status.FAILED).count(),
            "email_pending": qs.filter(status=NotificationDelivery.Status.PENDING).count(),
            "email_skipped": qs.filter(status=NotificationDelivery.Status.SKIPPED).count(),
        }


class NotificationCampaignCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    body = serializers.CharField()
    category = serializers.ChoiceField(
        choices=NotificationCampaign.Category.choices,
        default=NotificationCampaign.Category.ANNOUNCEMENT,
    )
    channels = serializers.ListField(
        child=serializers.ChoiceField(choices=["in_app", "email", "banner"]),
        default=["in_app"],
    )
    audience = serializers.JSONField(default=dict)
    is_pinned = serializers.BooleanField(default=False)
    action_url = serializers.CharField(required=False, allow_blank=True, default="")
    # ---- Banner config (used when "banner" is in channels) ----
    banner_variant = serializers.ChoiceField(
        choices=NotificationCampaign.BannerVariant.choices,
        default=NotificationCampaign.BannerVariant.INFO,
        required=False,
    )
    banner_dismissible = serializers.BooleanField(default=True, required=False)
    banner_starts_at = serializers.DateTimeField(required=False, allow_null=True)
    banner_ends_at = serializers.DateTimeField(required=False, allow_null=True)


class BannerNotificationSerializer(serializers.ModelSerializer):
    """Compact representation tailored to the header banner host."""

    campaign_id = serializers.UUIDField(source="campaign.id", read_only=True)
    title = serializers.CharField(source="campaign.title", read_only=True)
    body = serializers.CharField(source="campaign.body", read_only=True)
    category = serializers.CharField(source="campaign.category", read_only=True)
    action_url = serializers.CharField(read_only=True)
    variant = serializers.CharField(source="campaign.banner_variant", read_only=True)
    dismissible = serializers.BooleanField(
        source="campaign.banner_dismissible", read_only=True
    )
    starts_at = serializers.DateTimeField(
        source="campaign.banner_starts_at", read_only=True
    )
    ends_at = serializers.DateTimeField(
        source="campaign.banner_ends_at", read_only=True
    )

    class Meta:
        model = Notification
        fields = [
            "id",
            "campaign_id",
            "title",
            "body",
            "category",
            "action_url",
            "variant",
            "dismissible",
            "starts_at",
            "ends_at",
        ]
        read_only_fields = fields


class AnnouncementSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationCampaign
        fields = [
            "id",
            "title",
            "body",
            "category",
            "sent_at",
            "is_pinned",
            "recipient_count",
        ]


class NotificationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationRule
        fields = [
            "id",
            "event_type",
            "enabled",
            "title_template",
            "body_template",
            "category",
            "channels",
            "audience_override",
            "lead_days",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "event_type", "created_at", "updated_at"]


class UserNotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserNotificationPreference
        fields = ["id", "email_enabled", "muted_categories"]
        read_only_fields = ["id"]


class TenantNotificationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantNotificationSettings
        fields = ["id", "grade_publish_enabled", "payment_reminder_lead_days"]
        read_only_fields = ["id"]

from django.contrib import admin

from notifications.models import (
    Notification,
    NotificationCampaign,
    NotificationDelivery,
    NotificationRule,
    TenantNotificationSettings,
    UserNotificationPreference,
)


@admin.register(NotificationCampaign)
class NotificationCampaignAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "status", "recipient_count", "sent_at", "created_at"]
    list_filter = ["category", "status", "source"]
    search_fields = ["title", "body"]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["campaign", "recipient", "read_at", "created_at"]
    list_filter = ["read_at"]


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ["campaign", "recipient", "channel", "status", "sent_at"]
    list_filter = ["status", "channel"]


@admin.register(NotificationRule)
class NotificationRuleAdmin(admin.ModelAdmin):
    list_display = ["event_type", "enabled", "category", "lead_days"]


@admin.register(UserNotificationPreference)
class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "email_enabled"]


@admin.register(TenantNotificationSettings)
class TenantNotificationSettingsAdmin(admin.ModelAdmin):
    list_display = ["grade_publish_enabled", "payment_reminder_lead_days"]

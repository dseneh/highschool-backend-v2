from django.db import models

from common.models import BaseModel


class NotificationCampaign(BaseModel):
    class Category(models.TextChoices):
        ANNOUNCEMENT = "announcement", "Announcement"
        ALERT = "alert", "Alert"
        GRADE = "grade", "Grade"
        FINANCE = "finance", "Finance"
        SYSTEM = "system", "System"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        RULE = "rule", "Rule"
        SYSTEM = "system", "System"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    class BannerVariant(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        SUCCESS = "success", "Success"

    title = models.CharField(max_length=255)
    body = models.TextField()
    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.ANNOUNCEMENT,
        db_index=True,
    )
    channels = models.JSONField(
        default=list,
        help_text='e.g. ["in_app", "email"]',
    )
    audience = models.JSONField(default=dict)
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.MANUAL,
    )
    rule = models.ForeignKey(
        "notifications.NotificationRule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    recipient_count = models.PositiveIntegerField(default=0)
    is_pinned = models.BooleanField(default=False)

    # ---- Banner channel (header strip) ----
    deliver_banner = models.BooleanField(
        default=False,
        help_text="If true, emit this campaign as a header banner for recipients.",
    )
    banner_variant = models.CharField(
        max_length=16,
        choices=BannerVariant.choices,
        default=BannerVariant.INFO,
        blank=True,
    )
    banner_dismissible = models.BooleanField(
        default=True,
        help_text="If false, users cannot manually dismiss this banner (it only goes away after banner_ends_at).",
    )
    banner_starts_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the banner becomes visible. Null = visible immediately.",
    )
    banner_ends_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the banner stops showing. Null = no auto-expiration.",
    )

    class Meta:
        db_table = "notification_campaign"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Notification(BaseModel):
    campaign = models.ForeignKey(
        NotificationCampaign,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    recipient = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="inbox_notifications",
        to_field="id",
    )
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    action_url = models.CharField(max_length=500, blank=True, default="")
    banner_dismissed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this user dismissed the banner channel (if any).",
    )

    class Meta:
        db_table = "notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "read_at"]),
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["recipient", "banner_dismissed_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "recipient"],
                name="uniq_notification_campaign_recipient",
            )
        ]

    def __str__(self):
        return f"{self.campaign.title} -> {self.recipient_id}"


class NotificationDelivery(BaseModel):
    class Channel(models.TextChoices):
        EMAIL = "email", "Email"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    campaign = models.ForeignKey(
        NotificationCampaign,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    recipient = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="notification_deliveries",
        to_field="id",
    )
    channel = models.CharField(
        max_length=16,
        choices=Channel.choices,
        default=Channel.EMAIL,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification_delivery"
        indexes = [
            models.Index(fields=["campaign", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "recipient", "channel"],
                name="uniq_notification_delivery_campaign_recipient_channel",
            )
        ]


class NotificationRule(BaseModel):
    class EventType(models.TextChoices):
        GRADE_PUBLISHED = "grade_published", "Grade published"
        PAYMENT_DUE_REMINDER = "payment_due_reminder", "Payment due reminder"
        ATTENDANCE_ABSENT = "attendance_absent", "Attendance absent"

    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        unique=True,
    )
    enabled = models.BooleanField(default=False)
    title_template = models.CharField(max_length=255, blank=True, default="")
    body_template = models.TextField(blank=True, default="")
    category = models.CharField(
        max_length=32,
        choices=NotificationCampaign.Category.choices,
        default=NotificationCampaign.Category.SYSTEM,
    )
    channels = models.JSONField(default=list)
    audience_override = models.JSONField(default=dict, blank=True)
    lead_days = models.PositiveSmallIntegerField(
        default=7,
        help_text="Days before due date for payment reminders",
    )

    class Meta:
        db_table = "notification_rule"
        ordering = ["event_type"]

    def __str__(self):
        return f"{self.event_type} ({'on' if self.enabled else 'off'})"


class UserNotificationPreference(BaseModel):
    user = models.OneToOneField(
        "users.User",
        on_delete=models.CASCADE,
        related_name="notification_preference",
        to_field="id",
    )
    email_enabled = models.BooleanField(default=True)
    muted_categories = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "user_notification_preference"

    def __str__(self):
        return f"prefs:{self.user_id}"


class TenantNotificationSettings(BaseModel):
    """Per-tenant notification automation toggles (singleton row)."""

    grade_publish_enabled = models.BooleanField(default=True)
    payment_reminder_lead_days = models.PositiveSmallIntegerField(default=7)

    class Meta:
        db_table = "tenant_notification_settings"
        verbose_name_plural = "Tenant notification settings"

    @classmethod
    def get_solo(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj

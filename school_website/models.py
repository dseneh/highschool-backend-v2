from django.core.exceptions import ValidationError
from django.db import models

from common.models import BaseModel


class WebsiteSettings(BaseModel):
    class Template(models.TextChoices):
        HERITAGE = "heritage", "Heritage"
        MODERN = "modern", "Modern"
        CAMPUS = "campus", "Campus"
        SCHOLAR = "scholar", "Scholar"

    key = models.CharField(max_length=20, unique=True, default="default", editable=False)
    template = models.CharField(max_length=20, choices=Template.choices, default=Template.MODERN)
    design_tokens = models.JSONField(default=dict, blank=True)
    seo_defaults = models.JSONField(default=dict, blank=True)
    contact_overrides = models.JSONField(default=dict, blank=True)
    social_links = models.JSONField(default=list, blank=True)
    admissions_cta = models.JSONField(default=dict, blank=True)
    published_revision = models.ForeignKey(
        "school_website.WebsiteRevision", on_delete=models.SET_NULL, null=True,
        blank=True, related_name="published_for_settings",
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "website_settings"
        verbose_name_plural = "Website settings"

    def clean(self):
        if self.pk and WebsiteSettings.objects.exclude(pk=self.pk).exists():
            raise ValidationError("Only one website settings record is allowed per school.")

    @classmethod
    def get_solo(cls):
        obj, _created = cls.objects.get_or_create(key="default")
        return obj


class WebsitePage(BaseModel):
    class PageType(models.TextChoices):
        HOME = "home", "Home"
        STANDARD = "standard", "Standard"
        NEWS = "news", "News"
        EVENTS = "events", "Events"
        CONTACT = "contact", "Contact"
        ADMISSIONS = "admissions", "Admissions"

    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=160, unique=True)
    page_type = models.CharField(max_length=20, choices=PageType.choices, default=PageType.STANDARD)
    navigation_visible = models.BooleanField(default=True)
    navigation_order = models.PositiveSmallIntegerField(default=0)
    seo = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "website_page"
        ordering = ["navigation_order", "title"]
        indexes = [models.Index(fields=["active", "navigation_order"])]


class WebsiteSection(BaseModel):
    page = models.ForeignKey(WebsitePage, on_delete=models.CASCADE, related_name="sections")
    block_type = models.CharField(max_length=50)
    position = models.PositiveSmallIntegerField(default=0)
    variant = models.CharField(max_length=50, blank=True, default="")
    content = models.JSONField(default=dict)

    class Meta:
        db_table = "website_section"
        ordering = ["position", "created_at"]
        constraints = [models.UniqueConstraint(fields=["page", "position"], name="uniq_website_page_section_position")]
        indexes = [models.Index(fields=["page", "active", "position"])]


class WebsiteNavigationItem(BaseModel):
    class DestinationType(models.TextChoices):
        PAGE = "page", "Page"
        URL = "url", "External URL"

    label = models.CharField(max_length=80)
    destination_type = models.CharField(max_length=10, choices=DestinationType.choices, default=DestinationType.PAGE)
    page = models.ForeignKey(WebsitePage, on_delete=models.CASCADE, null=True, blank=True, related_name="navigation_items")
    url = models.URLField(blank=True, default="")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "website_navigation_item"
        ordering = ["position", "label"]

    def clean(self):
        if self.destination_type == self.DestinationType.PAGE and not self.page_id:
            raise ValidationError({"page": "A page is required for page destinations."})
        if self.destination_type == self.DestinationType.URL and not self.url:
            raise ValidationError({"url": "A URL is required for external destinations."})


class WebsiteMedia(BaseModel):
    file = models.FileField(upload_to="website/media")
    display_name = models.CharField(max_length=255)
    alt_text = models.CharField(max_length=255, blank=True, default="")
    purpose = models.CharField(max_length=50, blank=True, default="")
    focal_point = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "website_media"
        ordering = ["-created_at"]


class WebsiteRevision(BaseModel):
    revision_number = models.PositiveIntegerField(unique=True)
    snapshot = models.JSONField(default=dict)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "website_revision"
        ordering = ["-revision_number"]

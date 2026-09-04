from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

from school_website.models import WebsiteMedia, WebsiteNavigationItem, WebsitePage, WebsiteSection, WebsiteSettings


WEBSITE_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
WEBSITE_IMAGE_MAX_BYTES = 10 * 1024 * 1024


ALLOWED_BLOCK_TYPES = {
    "about", "achievements", "admissions", "announcements", "contact",
    "custom_rich_text", "events", "facilities", "faq", "gallery", "hero",
    "history", "leadership", "mission_vision_values", "programs", "statistics",
    "testimonials",
}


class WebsiteSectionSerializer(serializers.ModelSerializer):
    def validate_block_type(self, value):
        if value not in ALLOWED_BLOCK_TYPES:
            raise serializers.ValidationError("Unsupported website block type.")
        return value

    class Meta:
        model = WebsiteSection
        fields = ["id", "page", "block_type", "position", "variant", "content", "active"]


class WebsitePageSerializer(serializers.ModelSerializer):
    sections = WebsiteSectionSerializer(many=True, read_only=True)

    class Meta:
        model = WebsitePage
        fields = ["id", "title", "slug", "page_type", "navigation_visible", "navigation_order", "seo", "active", "sections"]


class WebsiteNavigationItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebsiteNavigationItem
        fields = ["id", "label", "destination_type", "page", "url", "parent", "position", "active"]

    def validate(self, attrs):
        destination_type = attrs.get("destination_type", getattr(self.instance, "destination_type", None))
        page = attrs.get("page", getattr(self.instance, "page", None))
        url = attrs.get("url", getattr(self.instance, "url", ""))
        if destination_type == WebsiteNavigationItem.DestinationType.PAGE and not page:
            raise serializers.ValidationError({"page": "A page is required."})
        if destination_type == WebsiteNavigationItem.DestinationType.URL and not url:
            raise serializers.ValidationError({"url": "A URL is required."})
        return attrs


class WebsiteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebsiteSettings
        fields = ["id", "template", "design_tokens", "seo_defaults", "contact_overrides", "social_links", "admissions_cta", "published_revision", "published_at"]
        read_only_fields = ["published_revision", "published_at"]


class WebsiteMediaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = WebsiteMedia
        fields = [
            "id", "file", "url", "display_name", "alt_text", "purpose",
            "focal_point", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "url", "created_at", "updated_at"]
        extra_kwargs = {"file": {"write_only": True}}

    def get_url(self, obj):
        request = self.context.get("request")
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url

    def validate_file(self, upload):
        if upload.size > WEBSITE_IMAGE_MAX_BYTES:
            raise serializers.ValidationError("Image must be 10 MB or smaller.")
        content_type = (getattr(upload, "content_type", "") or "").lower()
        if content_type not in WEBSITE_IMAGE_MIME_TYPES:
            raise serializers.ValidationError("Use a JPEG, PNG, WebP, or GIF image.")
        try:
            upload.seek(0)
            image = Image.open(upload)
            image.verify()
            upload.seek(0)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise serializers.ValidationError("The selected file is not a valid image.") from exc
        return upload

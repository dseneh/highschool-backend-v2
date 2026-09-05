from io import BytesIO
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image
from rest_framework import serializers

from school_website.models import WebsiteSettings
from school_website.serializers import WebsiteMediaSerializer, WebsiteSectionSerializer
from school_website.services import (
    public_website_fallback,
    reordered_items,
    tenant_website_defaults,
)


class WebsiteContractTests(SimpleTestCase):
    def test_exactly_four_supported_template_keys(self):
        self.assertEqual(
            {value for value, _label in WebsiteSettings.Template.choices},
            {"heritage", "modern", "campus", "scholar"},
        )

    def test_unknown_section_block_is_rejected(self):
        serializer = WebsiteSectionSerializer()
        with self.assertRaises(serializers.ValidationError):
            serializer.validate_block_type("custom_script")

    def test_media_rejects_non_image_content(self):
        upload = SimpleUploadedFile(
            "photo.png", b"not an image", content_type="image/png"
        )
        serializer = WebsiteMediaSerializer(
            data={"file": upload, "display_name": "Photo"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("file", serializer.errors)

    def test_media_accepts_valid_png(self):
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        upload = SimpleUploadedFile(
            "photo.png", buffer.getvalue(), content_type="image/png"
        )
        serializer = WebsiteMediaSerializer(
            data={"file": upload, "display_name": "Photo"}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_tenant_identity_and_theme_are_reused(self):
        tenant = SimpleNamespace(
            name="Example Academy",
            short_name="EA",
            slogan="Learn well",
            description="A community school.",
            theme_color="#123456",
            theme_config={},
            logo=None,
            email="hello@example.test",
            phone="123",
            address="1 Main Street",
            city="Monrovia",
            state="",
            country="Liberia",
            postal_code="",
        )
        defaults = tenant_website_defaults(tenant)
        self.assertEqual(defaults["design_tokens"]["school_name"], "Example Academy")
        self.assertEqual(defaults["design_tokens"]["primary_color"], "#123456")
        self.assertEqual(
            defaults["contact"]["address"], "1 Main Street, Monrovia, Liberia"
        )

    def test_disabled_website_has_minimal_public_fallback(self):
        tenant = SimpleNamespace(
            name="Example Academy",
            short_name=None,
            slogan=None,
            description=None,
            theme_color=None,
            theme_config={"colors": {"primary": "#654321"}},
            logo=None,
            email=None,
            phone=None,
            address=None,
            city=None,
            state=None,
            country=None,
            postal_code=None,
        )
        fallback = public_website_fallback(tenant=tenant, enabled=False)
        self.assertFalse(fallback["enabled"])
        self.assertFalse(fallback["published"])
        self.assertEqual(fallback["pages"], [])
        self.assertEqual(fallback["design_tokens"]["primary_color"], "#654321")

    def test_sections_can_be_reordered_without_mutating_input(self):
        original = ["hero", "about", "contact"]
        self.assertEqual(
            reordered_items(original, "contact", 1),
            ["hero", "contact", "about"],
        )
        self.assertEqual(original, ["hero", "about", "contact"])

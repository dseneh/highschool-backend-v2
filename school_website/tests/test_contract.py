from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image
from rest_framework import serializers

from school_website.models import WebsiteSettings
from school_website.serializers import WebsiteMediaSerializer, WebsiteSectionSerializer


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
        upload = SimpleUploadedFile("photo.png", b"not an image", content_type="image/png")
        serializer = WebsiteMediaSerializer(data={"file": upload, "display_name": "Photo"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("file", serializer.errors)

    def test_media_accepts_valid_png(self):
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        upload = SimpleUploadedFile("photo.png", buffer.getvalue(), content_type="image/png")
        serializer = WebsiteMediaSerializer(data={"file": upload, "display_name": "Photo"})
        self.assertTrue(serializer.is_valid(), serializer.errors)

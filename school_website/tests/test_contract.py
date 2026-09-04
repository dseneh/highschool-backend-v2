from django.test import SimpleTestCase
from rest_framework import serializers

from school_website.models import WebsiteSettings
from school_website.serializers import WebsiteSectionSerializer


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

from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
import subprocess
import sys

from django.test import SimpleTestCase
from rest_framework import serializers

from common.update_utils import get_update_value, validate_partial_update


class ExampleUpdateSerializer(serializers.Serializer):
    name = serializers.CharField()
    notes = serializers.CharField(allow_null=True, allow_blank=True)
    enabled = serializers.BooleanField(default=True)
    count = serializers.IntegerField(min_value=0)


class PartialUpdateUtilityTests(SimpleTestCase):
    def setUp(self):
        self.instance = SimpleNamespace(
            name="Existing", notes="Keep", enabled=False, count=5
        )

    def test_validates_only_supplied_fields_and_skips_defaults(self):
        payload = {"name": "Edited"}
        serializer = validate_partial_update(
            ExampleUpdateSerializer, self.instance, payload
        )
        self.assertEqual(serializer.validated_data, {"name": "Edited"})
        self.assertEqual(payload, {"name": "Edited"})
        self.assertEqual(self.instance.name, "Existing")

    def test_factory_receives_context_and_forces_partial_for_put(self):
        factory = Mock(wraps=ExampleUpdateSerializer)
        context = {"request": SimpleNamespace(method="PUT")}
        serializer = validate_partial_update(
            factory, self.instance, {"notes": "Edited"},
            context=context, partial=False,
        )
        self.assertTrue(serializer.partial)
        self.assertIs(serializer.context, context)
        self.assertEqual(serializer.validated_data, {"notes": "Edited"})

    def test_explicit_empty_values_are_not_treated_as_omitted(self):
        payload = {"notes": None, "enabled": False, "count": 0}
        serializer = validate_partial_update(
            ExampleUpdateSerializer, self.instance, payload
        )
        self.assertEqual(serializer.validated_data, payload)
        for value in (None, False, 0, ""):
            with self.subTest(value=value):
                self.assertEqual(
                    get_update_value(self.instance, {"notes": value}, "notes"),
                    value,
                )

    def test_invalid_supplied_value_still_fails(self):
        with self.assertRaises(serializers.ValidationError) as error:
            validate_partial_update(
                ExampleUpdateSerializer, self.instance, {"count": -1}
            )
        self.assertIn("count", error.exception.detail)

    def test_create_cannot_use_update_helper(self):
        with self.assertRaises(ValueError):
            validate_partial_update(ExampleUpdateSerializer, None, {"name": "New"})
        serializer = ExampleUpdateSerializer(data={"name": "New"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("notes", serializer.errors)
        self.assertIn("count", serializer.errors)

    def test_empty_update_does_not_inject_existing_values(self):
        serializer = validate_partial_update(ExampleUpdateSerializer, self.instance, {})
        self.assertEqual(serializer.validated_data, {})

    def test_effective_value_does_not_expand_payload(self):
        payload = {"name": "Edited"}
        self.assertEqual(get_update_value(self.instance, payload, "notes"), "Keep")
        self.assertEqual(get_update_value(None, payload, "notes", "Default"), "Default")
        self.assertEqual(payload, {"name": "Edited"})

    def test_mapping_instance_keeps_missing_and_explicit_null_distinct(self):
        self.assertEqual(get_update_value({"name": "Stored"}, {}, "name"), "Stored")
        self.assertIsNone(get_update_value({"name": "Stored"}, {"name": None}, "name"))

    def test_existing_error_response_paths_can_inspect_invalid_serializer(self):
        serializer = validate_partial_update(
            ExampleUpdateSerializer, self.instance, {"count": -1}, raise_exception=False
        )
        self.assertIn("count", serializer.errors)

    def test_shared_update_contract_against_private_database(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("partial_update_integration.py"))],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

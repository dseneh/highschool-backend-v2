from types import SimpleNamespace

from django.test import SimpleTestCase

from common.update_utils import comparable_value, filter_changed_data


class ChangedFieldUtilityTests(SimpleTestCase):
    def test_filters_unchanged_values(self):
        instance = SimpleNamespace(name="Operating", status="active")

        self.assertEqual(
            filter_changed_data(
                instance,
                {"name": "Operating", "status": "inactive"},
            ),
            {"status": "inactive"},
        )

    def test_compares_related_objects_by_primary_key(self):
        current_currency = SimpleNamespace(pk="usd")
        next_currency = SimpleNamespace(pk="usd")
        instance = SimpleNamespace(currency=current_currency)

        self.assertEqual(
            filter_changed_data(instance, {"currency": next_currency}),
            {},
        )

    def test_keeps_explicit_null_when_clearing_value(self):
        instance = SimpleNamespace(description="Old note")

        self.assertEqual(
            filter_changed_data(instance, {"description": None}),
            {"description": None},
        )

    def test_can_limit_comparison_to_selected_fields(self):
        instance = SimpleNamespace(name="Old", status="active")

        self.assertEqual(
            filter_changed_data(
                instance,
                {"name": "New", "status": "inactive"},
                fields={"status"},
            ),
            {"status": "inactive"},
        )

    def test_normalizes_nested_values(self):
        self.assertEqual(
            comparable_value({"currency": {"id": "usd"}, "tags": ["a", "b"]}),
            (("currency", (("id", "usd"),)), ("tags", ("a", "b"))),
        )

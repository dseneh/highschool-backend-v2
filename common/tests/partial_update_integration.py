"""Run the shared update contract against a private in-memory SQLite database.

Executed in a subprocess by test_partial_updates so these persistence tests
never connect to a tenant or require a configured PostgreSQL test server.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from django.apps import AppConfig
from django.conf import settings


class UpdateTestApp(AppConfig):
    name = "__main__"
    label = "update_contract"
    path = str(Path(__file__).parent)


settings.configure(
    SECRET_KEY="isolated-update-contract-tests",
    INSTALLED_APPS=["__main__.UpdateTestApp"],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    REST_FRAMEWORK={"UNAUTHENTICATED_USER": None},
    USE_TZ=True,
)

import django

django.setup()

from django.db import connection, models
from django.http import QueryDict
from django.test.utils import CaptureQueriesContext
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from common.update_utils import PartialUpdateModelSerializer, validate_model_update, validate_partial_update
from common.viewsets import PartialUpdateModelViewSet


class Record(models.Model):
    name = models.CharField(max_length=80)
    notes = models.TextField(null=True, blank=True)
    enabled = models.BooleanField(default=True)
    count = models.PositiveIntegerField(default=5)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    tags = models.ManyToManyField("self", symmetrical=False, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "update_contract"


class RecordSerializer(PartialUpdateModelSerializer):
    class Meta:
        model = Record
        fields = ["id", "name", "notes", "enabled", "count", "parent", "tags", "updated_at"]
        read_only_fields = ["id", "updated_at"]


class RecordViewSet(PartialUpdateModelViewSet):
    queryset = Record.objects.all()
    serializer_class = RecordSerializer
    authentication_classes = []
    permission_classes = []
    save_hook_calls = 0

    def perform_update(self, serializer):
        type(self).save_hook_calls += 1
        super().perform_update(serializer)


class PersistenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            editor.create_model(Record)

    def setUp(self):
        Record.objects.all().delete()
        self.record = Record.objects.create(name="Original", notes="Keep", enabled=False)
        RecordViewSet.save_hook_calls = 0

    def request(self, method, payload):
        request = getattr(APIRequestFactory(), method)("/records/1/", payload, format="json")
        return RecordViewSet.as_view({"put": "update", "patch": "partial_update"})(
            request, pk=self.record.pk
        )

    def test_put_and_patch_omit_required_name_and_preserve_save_hook(self):
        for method in ("put", "patch"):
            response = self.request(method, {"notes": method})
            self.assertEqual(response.status_code, 200, response.data)
            self.record.refresh_from_db()
            self.assertEqual(self.record.notes, method)
            self.assertEqual(self.record.name, "Original")
            self.assertFalse(self.record.enabled)
        self.assertEqual(RecordViewSet.save_hook_calls, 2)

    def test_stale_instance_cannot_overwrite_omitted_columns(self):
        stale = Record.objects.get(pk=self.record.pk)
        Record.objects.filter(pk=stale.pk).update(name="Changed by another request")
        validate_partial_update(RecordSerializer, stale, {"notes": "My edit"}).save()
        self.record.refresh_from_db()
        self.assertEqual(self.record.name, "Changed by another request")
        self.assertEqual(self.record.notes, "My edit")

    def test_sql_update_only_names_submitted_columns_and_audit_timestamp(self):
        with CaptureQueriesContext(connection) as queries:
            validate_partial_update(RecordSerializer, self.record, {"notes": "Edited"}).save()
        updates = [q["sql"] for q in queries if q["sql"].startswith("UPDATE")]
        self.assertEqual(len(updates), 1)
        self.assertIn('"notes"', updates[0])
        self.assertNotIn('"name"', updates[0])
        self.assertNotIn('"enabled"', updates[0])

    def test_unchanged_and_empty_updates_do_not_write(self):
        for payload in ({}, {"notes": "Keep"}):
            with CaptureQueriesContext(connection) as queries:
                validate_partial_update(RecordSerializer, self.record, payload).save()
            self.assertFalse(any(q["sql"].startswith("UPDATE") for q in queries))

    def test_null_zero_and_false_remain_explicit_values(self):
        self.record.enabled = True
        self.record.save()
        response = self.request("put", {"notes": None, "count": 0, "enabled": False})
        self.assertEqual(response.status_code, 200, response.data)
        self.record.refresh_from_db()
        self.assertIsNone(self.record.notes)
        self.assertEqual(self.record.count, 0)
        self.assertFalse(self.record.enabled)

    def test_invalid_fields_fail_without_any_write(self):
        for payload in ({"count": -1}, {"name": None}, {"parent": 99999}):
            response = self.request("patch", payload)
            self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(RecordViewSet.save_hook_calls, 0)
        self.record.refresh_from_db()
        self.assertEqual(self.record.name, "Original")

    def test_omitted_many_to_many_is_preserved_and_explicit_empty_list_clears(self):
        tag = Record.objects.create(name="Tag")
        self.record.tags.add(tag)
        self.request("put", {"notes": "Changed"})
        self.assertEqual(list(self.record.tags.all()), [tag])
        response = self.request("patch", {"tags": []})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(self.record.tags.exists())

    def test_many_to_many_replacement_and_prefetch_cache(self):
        first = Record.objects.create(name="First")
        second = Record.objects.create(name="Second")
        self.record.tags.add(first)
        RecordViewSet.queryset = Record.objects.prefetch_related("tags")
        try:
            response = self.request("put", {"tags": [second.pk]})
        finally:
            RecordViewSet.queryset = Record.objects.all()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["tags"], [second.pk])
        self.assertEqual(list(self.record.tags.all()), [second])

    def test_read_only_fields_are_not_writable(self):
        original_id = self.record.pk
        response = self.request("patch", {"id": 999, "notes": "Edited"})
        self.assertEqual(response.status_code, 200, response.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.pk, original_id)
        self.assertFalse(Record.objects.filter(pk=999).exists())

    def test_model_allowlist_validates_before_saving(self):
        with self.assertRaises(serializers.ValidationError):
            validate_model_update(self.record, {"notes": "Invalid sibling", "count": -1}, ["notes", "count"])
        self.record.refresh_from_db()
        self.assertEqual(self.record.notes, "Keep")
        serializer = validate_model_update(self.record, {"notes": "Allowed", "name": "Forbidden"}, ["notes"])
        serializer.save()
        self.record.refresh_from_db()
        self.assertEqual(self.record.name, "Original")

    def test_model_update_accepts_fk_id_and_resolved_object(self):
        parent = Record.objects.create(name="Parent")
        validate_model_update(self.record, {"parent_id": parent.pk}, ["parent_id"]).save()
        self.record.refresh_from_db()
        self.assertEqual(self.record.parent_id, parent.pk)
        validate_model_update(self.record, {"parent": None}, ["parent"]).save()
        self.record.refresh_from_db()
        self.assertIsNone(self.record.parent_id)
        validate_model_update(self.record, {"parent": parent}, ["parent"]).save()
        self.record.refresh_from_db()
        self.assertEqual(self.record.parent_id, parent.pk)

    def test_multipart_preserves_omitted_boolean_and_parses_false(self):
        self.record.enabled = True
        self.record.save()
        payload = QueryDict("notes=multipart")
        validate_model_update(self.record, payload, ["notes", "enabled"]).save()
        self.record.refresh_from_db()
        self.assertTrue(self.record.enabled)
        validate_model_update(self.record, QueryDict("enabled=false"), ["enabled"]).save()
        self.record.refresh_from_db()
        self.assertFalse(self.record.enabled)
        self.assertEqual(payload.urlencode(), "notes=multipart")

    def test_creation_keeps_required_fields(self):
        serializer = RecordSerializer(data={"notes": "Missing required name"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("name", serializer.errors)


if __name__ == "__main__":
    unittest.main()

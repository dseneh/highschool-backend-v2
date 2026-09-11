from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase, override_settings

from authorization.registry import load_permission_registry
from backups.models import TenantBackup, TenantRestoreRequest
from backups.serializers import (
    BackupRequestCreateSerializer,
    TenantBackupSerializer,
    TenantRestoreRequestSerializer,
)
from backups.views import PlatformRestoreRequestViewSet, TenantBackupViewSet, TenantRestoreRequestViewSet
from common.permissions import IsSuperAdmin


class BackupPermissionContractTests(SimpleTestCase):
    def test_backup_permissions_are_registered(self):
        permission_dir = Path(__file__).resolve().parents[2] / "authorization" / "permissions"
        registry = load_permission_registry(permission_dir)
        self.assertEqual(registry.require("backups.view").scopes, ["all"])
        create = registry.require("backups.create")
        self.assertEqual(create.scopes, ["all"])
        self.assertEqual(create.requires, ["backups.view"])
        delete = registry.require("backups.delete")
        self.assertEqual(delete.scopes, ["all"])
        self.assertEqual(delete.requires, ["backups.view"])
        restore = registry.require("restore.request")
        self.assertEqual(restore.scopes, ["all"])
        self.assertEqual(restore.requires, ["backups.view"])

    def test_tenant_backup_viewset_exposes_controlled_delete_only(self):
        self.assertEqual(TenantBackupViewSet.permission_map["request_restore"], "restore.request")
        self.assertEqual(TenantBackupViewSet.permission_map["destroy"], "backups.delete")
        self.assertEqual(
            TenantRestoreRequestViewSet.permission_map,
            {"list": "backups.view", "retrieve": "backups.view"},
        )
        self.assertIn("delete", TenantBackupViewSet.http_method_names)
        self.assertNotIn("put", TenantBackupViewSet.http_method_names)
        self.assertNotIn("patch", TenantBackupViewSet.http_method_names)
        self.assertNotIn("post", TenantRestoreRequestViewSet.http_method_names)

    def test_platform_restore_decisions_require_superadmin(self):
        self.assertEqual(PlatformRestoreRequestViewSet.permission_classes, [IsSuperAdmin])
        self.assertIn("post", PlatformRestoreRequestViewSet.http_method_names)


class BackupSerializerContractTests(SimpleTestCase):
    def test_sensitive_operational_fields_are_not_exposed(self):
        fields = set(TenantBackupSerializer.Meta.fields)
        self.assertNotIn("storage_key", fields)
        self.assertNotIn("error_message", fields)
        self.assertNotIn("schema_name", fields)
        self.assertNotIn("storage_provider", fields)

    def test_manual_backup_reason_is_required(self):
        serializer = BackupRequestCreateSerializer(data={"reason": ""})
        self.assertFalse(serializer.is_valid())
        serializer = BackupRequestCreateSerializer(data={"reason": "Before year-end adjustments"})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_restore_serializer_does_not_expose_operational_fields(self):
        fields = set(TenantRestoreRequestSerializer.Meta.fields)
        self.assertNotIn("schema_name", fields)
        self.assertNotIn("error_message", fields)
        self.assertNotIn("tenant_runtime_snapshot", fields)


class BackupServiceContractTests(SimpleTestCase):
    @patch("backups.services.subprocess.run")
    def test_pg_dump_schema_comes_from_tenant_not_caller(self, run):
        import inspect
        from backups.services import run_backup

        self.assertEqual(tuple(inspect.signature(run_backup).parameters), ("backup_id",))
        run.assert_not_called()

    def test_hash_stream_is_stable_for_integrity_verification(self):
        from backups.services import _hash_stream

        payload = b"ezy-school-tenant-backup"
        self.assertEqual(
            _hash_stream(BytesIO(payload)),
            "a0b6b4b1e24bacb9496a0b16ddafa21943e3535a2a374f4349580c2236680965",
        )

    @patch("backups.services.timezone.now")
    def test_storage_key_uses_schema_name(self, now):
        from backups.services import _storage_key

        now.return_value = datetime(2026, 9, 10, tzinfo=UTC)
        backup = SimpleNamespace(
            id=UUID("12345678-1234-5678-1234-567812345678"),
            schema_name="Dujar",
        )
        self.assertEqual(
            _storage_key(backup),
            "tenants/dujar/2026/09/12345678-1234-5678-1234-567812345678.dump",
        )

    def test_storage_key_rejects_public_schema(self):
        from backups.services import BackupError, _storage_key

        backup = SimpleNamespace(
            id=UUID("12345678-1234-5678-1234-567812345678"),
            schema_name="public",
        )
        with self.assertRaises(BackupError):
            _storage_key(backup)

    @override_settings(
        TENANT_BACKUP_RETENTION_MANUAL_DAYS=14,
        TENANT_BACKUP_RETENTION_SCHEDULED_DAYS=21,
        TENANT_BACKUP_RETENTION_PRE_RESTORE_DAYS=90,
        TENANT_BACKUP_RETENTION_SYSTEM_DAYS=7,
    )
    def test_retention_is_configuration_driven(self):
        from backups.services import _retention_days

        self.assertEqual(_retention_days(TenantBackup.BackupType.MANUAL), 14)
        self.assertEqual(_retention_days(TenantBackup.BackupType.SCHEDULED), 21)
        self.assertEqual(_retention_days(TenantBackup.BackupType.PRE_RESTORE), 90)
        self.assertEqual(_retention_days(TenantBackup.BackupType.SYSTEM), 7)

    @override_settings(TENANT_BACKUP_SCHEDULE_ENABLED=False)
    def test_scheduler_is_safe_off_by_default(self):
        from backups.services import queue_due_scheduled_backups

        self.assertEqual(queue_due_scheduled_backups(), [])


class RestoreServiceContractTests(SimpleTestCase):
    def test_restore_requires_safety_backup_phase(self):
        self.assertIn(TenantRestoreRequest.Status.SAFETY_BACKUP_PENDING, dict(TenantRestoreRequest.Status.choices))
        self.assertIn(TenantRestoreRequest.Status.READY_FOR_APPROVAL, dict(TenantRestoreRequest.Status.choices))
        self.assertIn(TenantRestoreRequest.Status.APPROVED, dict(TenantRestoreRequest.Status.choices))

    def test_restore_execution_accepts_only_request_id(self):
        import inspect
        from backups.restore_services import run_restore

        self.assertEqual(tuple(inspect.signature(run_restore).parameters), ("restore_request_id",))

    def test_restore_rejects_public_and_unsafe_schema_names(self):
        from backups.restore_services import _is_safe_schema

        self.assertTrue(_is_safe_schema("dujar"))
        self.assertTrue(_is_safe_schema("kipss_2026"))
        self.assertFalse(_is_safe_schema("public"))
        self.assertFalse(_is_safe_schema("dujar;drop schema public"))
        self.assertFalse(_is_safe_schema("dujar-school"))

    def test_rollback_schema_name_stays_within_postgres_identifier_limit(self):
        from backups.restore_services import _rollback_schema_name

        name = _rollback_schema_name("a" * 63, UUID("12345678-1234-5678-1234-567812345678"))
        self.assertLessEqual(len(name), 63)
        self.assertIn("__restore_rb_", name)


class RestoreTOCValidatorRegressionTests(SimpleTestCase):
    """Regression tests for TOC validator fix (Issue: false-positives on object names).
    
    Tests that:
    1. Object names containing forbidden words (database, subscription, etc.) do NOT false-positive
    2. Actual forbidden catalog types in the TOC ARE correctly rejected
    """

    def test_table_named_student_database_does_not_false_positive(self):
        """Table named 'student_database' should not trigger DATABASE filter."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public student_database postgres  
; 2345; INDEX SCHEMA public student_database_pkey postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(forbidden, [], "Object name containing 'database' word must not trigger filter")

    def test_function_named_validate_subscription_plan_does_not_false_positive(self):
        """Function named 'validate_subscription_plan' should not trigger SUBSCRIPTION filter."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; FUNCTION SCHEMA public validate_subscription_plan() postgres  
; 2345; FUNCTION SCHEMA public check_subscription_status() postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(forbidden, [], "Object name containing 'subscription' word must not trigger filter")

    def test_table_named_event_trigger_history_does_not_false_positive(self):
        """Table named 'event_trigger_history' should not trigger EVENT TRIGGER filter."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public event_trigger_history postgres  
; 2345; VIEW SCHEMA public event_trigger_logs postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(
            forbidden, [],
            "Object name containing 'event' and 'trigger' as separate words must not trigger filter",
        )

    def test_table_named_extension_metadata_does_not_false_positive(self):
        """Table named 'extension_metadata' should not trigger EXTENSION filter."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public extension_metadata postgres  
; 2345; COLUMN SCHEMA public extension_config postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(forbidden, [], "Object name containing 'extension' word must not trigger filter")

    def test_table_named_published_articles_does_not_false_positive(self):
        """Column named 'published_articles' should not trigger PUBLICATION filter."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public articles postgres  
; 2345; COLUMN SCHEMA public published_articles postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(forbidden, [], "Object name containing 'publication' word must not trigger filter")

    def test_actual_database_toc_entry_is_rejected(self):
        """Actual DATABASE entry in TOC must be rejected."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public users postgres  
; 2345; DATABASE mydb postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(len(forbidden), 1, "Actual DATABASE entry must be detected")
        self.assertIn("[DATABASE", forbidden[0], "Error message must include DATABASE type")

    def test_actual_extension_toc_entry_is_rejected(self):
        """Actual EXTENSION entry in TOC must be rejected."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public users postgres  
; 2345; EXTENSION uuid-ossp postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(len(forbidden), 1, "Actual EXTENSION entry must be detected")
        self.assertIn("[EXTENSION", forbidden[0], "Error message must include EXTENSION type")

    def test_actual_event_trigger_toc_entry_is_rejected(self):
        """Actual EVENT TRIGGER entry in TOC must be rejected."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public users postgres  
; 2345; EVENT TRIGGER log_schema_changes postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(len(forbidden), 1, "Actual EVENT TRIGGER entry must be detected")
        self.assertIn("[EVENT TRIGGER", forbidden[0], "Error message must include EVENT TRIGGER type")

    def test_actual_publication_toc_entry_is_rejected(self):
        """Actual PUBLICATION entry in TOC must be rejected."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public users postgres  
; 2345; PUBLICATION all_tables postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(len(forbidden), 1, "Actual PUBLICATION entry must be detected")
        self.assertIn("[PUBLICATION", forbidden[0], "Error message must include PUBLICATION type")

    def test_actual_subscription_toc_entry_is_rejected(self):
        """Actual SUBSCRIPTION entry in TOC must be rejected."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public users postgres  
; 2345; SUBSCRIPTION remote_sync postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(len(forbidden), 1, "Actual SUBSCRIPTION entry must be detected")
        self.assertIn("[SUBSCRIPTION", forbidden[0], "Error message must include SUBSCRIPTION type")

    def test_multiple_forbidden_entries_are_all_detected(self):
        """Multiple forbidden entries must all be detected."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public users postgres  
; 2345; DATABASE mydb postgres  
; 3456; EXTENSION uuid-ossp postgres  
; 4567; PUBLICATION all_tables postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(len(forbidden), 3, "All forbidden entries must be detected")

    def test_mixed_safe_and_forbidden_objects_only_flags_forbidden(self):
        """Safe objects mixed with forbidden ones only flag the forbidden ones."""
        from backups.restore_services import _find_forbidden_toc_entries

        toc = """; 1234; TABLE SCHEMA public users postgres  
; 2345; COLUMN SCHEMA public user_id postgres  
; 3456; FUNCTION SCHEMA public get_user_by_database_name() postgres  
; 4567; DATABASE mydb postgres  
; 5678; INDEX SCHEMA public users_pkey postgres  
"""
        forbidden = _find_forbidden_toc_entries(toc)
        self.assertEqual(len(forbidden), 1, "Only actual DATABASE entry should be detected")
        self.assertIn("[DATABASE", forbidden[0])
        self.assertNotIn("FUNCTION", forbidden[0])


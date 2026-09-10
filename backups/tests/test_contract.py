from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase, override_settings

from authorization.registry import load_permission_registry
from backups.models import TenantBackup, TenantRestoreRequest
from backups.serializers import TenantBackupSerializer, TenantRestoreRequestSerializer
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
        restore = registry.require("restore.request")
        self.assertEqual(restore.scopes, ["all"])
        self.assertEqual(restore.requires, ["backups.view"])

    def test_tenant_restore_viewset_remains_read_only(self):
        self.assertEqual(TenantBackupViewSet.permission_map["request_restore"], "restore.request")
        self.assertEqual(
            TenantRestoreRequestViewSet.permission_map,
            {"list": "backups.view", "retrieve": "backups.view"},
        )
        self.assertNotIn("delete", TenantBackupViewSet.http_method_names)
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

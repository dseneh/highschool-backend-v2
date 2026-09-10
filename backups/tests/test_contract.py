from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from authorization.registry import load_permission_registry
from backups.models import TenantBackup
from backups.serializers import TenantBackupSerializer
from backups.views import TenantBackupViewSet


class BackupPermissionContractTests(SimpleTestCase):
    def test_backup_permissions_are_registered(self):
        permission_dir = Path(__file__).resolve().parents[2] / "authorization" / "permissions"
        registry = load_permission_registry(permission_dir)
        self.assertEqual(registry.require("backups.view").scopes, ("all",))
        create = registry.require("backups.create")
        self.assertEqual(create.scopes, ("all",))
        self.assertEqual(create.requires, ("backups.view",))

    def test_viewset_is_read_only_except_for_create(self):
        self.assertEqual(
            TenantBackupViewSet.permission_map,
            {"list": "backups.view", "retrieve": "backups.view", "create": "backups.create"},
        )
        self.assertNotIn("delete", TenantBackupViewSet.http_method_names)
        self.assertNotIn("put", TenantBackupViewSet.http_method_names)
        self.assertNotIn("patch", TenantBackupViewSet.http_method_names)


class BackupSerializerContractTests(SimpleTestCase):
    def test_sensitive_operational_fields_are_not_exposed(self):
        fields = set(TenantBackupSerializer.Meta.fields)
        self.assertNotIn("storage_key", fields)
        self.assertNotIn("error_message", fields)
        self.assertNotIn("schema_name", fields)
        self.assertNotIn("storage_provider", fields)


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

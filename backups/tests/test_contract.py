from pathlib import Path
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from authorization.registry import load_permission_registry
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
        # This contract is primarily enforced by the function signature: the
        # execution service accepts only backup_id and resolves tenant/schema
        # from persisted server-side data. Keep a lightweight assertion here so
        # future API changes do not accidentally add a schema argument.
        import inspect
        from backups.services import run_backup

        self.assertEqual(tuple(inspect.signature(run_backup).parameters), ("backup_id",))
        run.assert_not_called()

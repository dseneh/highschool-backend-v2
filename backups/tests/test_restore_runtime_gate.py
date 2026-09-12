from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from backups.restore_services import _lock_tenant_runtime, _restore_tenant_runtime


class RestoreRuntimeGateTests(SimpleTestCase):
    @patch("backups.restore_services.timezone.now")
    def test_restoration_gate_does_not_change_operational_runtime(self, now):
        started_at = object()
        now.return_value = started_at
        tenant = SimpleNamespace(
            active=True,
            maintenance_mode=False,
            restoration_in_progress=False,
            restoration_started_at=None,
            restoration_request_id=None,
            disabled_access_allow_tenant_admins=True,
            disabled_access_allowed_users=["owner@example.com"],
            save=Mock(),
        )
        restore_request = SimpleNamespace(
            id=uuid4(),
            tenant=tenant,
            tenant_runtime_snapshot={},
            save=Mock(),
        )

        _lock_tenant_runtime(restore_request)

        self.assertTrue(tenant.active)
        self.assertFalse(tenant.maintenance_mode)
        self.assertTrue(tenant.disabled_access_allow_tenant_admins)
        self.assertEqual(tenant.disabled_access_allowed_users, ["owner@example.com"])
        self.assertTrue(tenant.restoration_in_progress)
        self.assertIs(tenant.restoration_started_at, started_at)
        self.assertEqual(tenant.restoration_request_id, restore_request.id)
        self.assertEqual(
            restore_request.tenant_runtime_snapshot,
            {"restoration_gate_only": True},
        )
        tenant.save.assert_called_once_with(
            update_fields=[
                "restoration_in_progress",
                "restoration_started_at",
                "restoration_request_id",
            ]
        )

        tenant.save.reset_mock()
        _restore_tenant_runtime(restore_request)

        self.assertTrue(tenant.active)
        self.assertFalse(tenant.maintenance_mode)
        self.assertTrue(tenant.disabled_access_allow_tenant_admins)
        self.assertEqual(tenant.disabled_access_allowed_users, ["owner@example.com"])
        self.assertFalse(tenant.restoration_in_progress)
        self.assertIsNone(tenant.restoration_started_at)
        self.assertIsNone(tenant.restoration_request_id)
        tenant.save.assert_called_once_with(
            update_fields=[
                "restoration_in_progress",
                "restoration_started_at",
                "restoration_request_id",
            ]
        )

    def test_cleanup_restores_runtime_changed_by_older_deployment(self):
        tenant = SimpleNamespace(
            active=False,
            maintenance_mode=True,
            restoration_in_progress=True,
            restoration_started_at=object(),
            restoration_request_id=uuid4(),
            disabled_access_allow_tenant_admins=False,
            disabled_access_allowed_users=[],
            save=Mock(),
        )
        restore_request = SimpleNamespace(
            tenant=tenant,
            tenant_runtime_snapshot={
                "active": True,
                "maintenance_mode": False,
                "disabled_access_allow_tenant_admins": True,
                "disabled_access_allowed_users": ["owner@example.com"],
            },
        )

        _restore_tenant_runtime(restore_request)

        self.assertTrue(tenant.active)
        self.assertFalse(tenant.maintenance_mode)
        self.assertTrue(tenant.disabled_access_allow_tenant_admins)
        self.assertEqual(tenant.disabled_access_allowed_users, ["owner@example.com"])
        self.assertFalse(tenant.restoration_in_progress)

from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from backups.restore_services import _lock_tenant_runtime, _restore_tenant_runtime


class RestoreRuntimeGateTests(SimpleTestCase):
    @patch("backups.restore_services.timezone.now")
    def test_lock_and_restore_preserve_prior_tenant_runtime(self, now):
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

        self.assertFalse(tenant.active)
        self.assertTrue(tenant.maintenance_mode)
        self.assertTrue(tenant.restoration_in_progress)
        self.assertIs(tenant.restoration_started_at, started_at)
        self.assertEqual(tenant.restoration_request_id, restore_request.id)

        _restore_tenant_runtime(restore_request)

        self.assertTrue(tenant.active)
        self.assertFalse(tenant.maintenance_mode)
        self.assertFalse(tenant.restoration_in_progress)
        self.assertIsNone(tenant.restoration_started_at)
        self.assertIsNone(tenant.restoration_request_id)
        self.assertEqual(tenant.disabled_access_allowed_users, ["owner@example.com"])

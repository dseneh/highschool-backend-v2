from datetime import datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from backups.models import BackupPlatformSettings
from backups.policies import BackupPolicyError, calculate_next_run
from backups.policy_permissions import TenantBackupCapabilityPermission


class BackupScheduleCalculationTests(SimpleTestCase):
    def test_daily_schedule_uses_configured_local_time(self):
        policy = SimpleNamespace(
            timezone="UTC",
            scheduled_time=time(2, 0),
            frequency=BackupPlatformSettings.Frequency.DAILY,
        )
        after = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
        result = calculate_next_run(policy, after=after)
        self.assertEqual(result, datetime(2026, 9, 12, 2, 0, tzinfo=timezone.utc))

    def test_weekly_schedule_advances_seven_days_after_wall_clock_passes(self):
        policy = SimpleNamespace(
            timezone="UTC",
            scheduled_time=time(2, 0),
            frequency=BackupPlatformSettings.Frequency.WEEKLY,
        )
        after = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
        result = calculate_next_run(policy, after=after)
        self.assertEqual(result, datetime(2026, 9, 18, 2, 0, tzinfo=timezone.utc))

    def test_invalid_timezone_is_rejected(self):
        policy = SimpleNamespace(
            timezone="Definitely/Not-A-Timezone",
            scheduled_time=time(2, 0),
            frequency=BackupPlatformSettings.Frequency.DAILY,
        )
        with self.assertRaises(BackupPolicyError):
            calculate_next_run(policy, after=datetime(2026, 9, 11, tzinfo=timezone.utc))


class BackupCapabilityPermissionTests(SimpleTestCase):
    def _view(self, action):
        return SimpleNamespace(action=action)

    def _request(self, *, superuser=False):
        return SimpleNamespace(user=SimpleNamespace(is_authenticated=True, is_superuser=superuser))

    def test_platform_superuser_bypasses_tenant_capability_gate(self):
        permission = TenantBackupCapabilityPermission()
        self.assertTrue(permission.has_permission(self._request(superuser=True), self._view("create")))

    @patch("backups.policy_permissions.connection")
    @patch("backups.policy_permissions.schema_context")
    @patch("backups.policy_permissions.Tenant.objects.get")
    @patch("backups.policy_permissions.effective_policy")
    def test_disabled_manual_backup_is_denied(self, effective_policy, tenant_get, schema_context, connection):
        connection.schema_name = "demo"
        tenant_get.return_value = SimpleNamespace(schema_name="demo")
        schema_context.return_value.__enter__.return_value = None
        effective_policy.return_value = SimpleNamespace(manual_backups_allowed=False)
        permission = TenantBackupCapabilityPermission()
        self.assertFalse(permission.has_permission(self._request(), self._view("create")))
        self.assertIn("Manual backups", permission.message)

    @patch("backups.policy_permissions.connection")
    @patch("backups.policy_permissions.schema_context")
    @patch("backups.policy_permissions.Tenant.objects.get")
    @patch("backups.policy_permissions.effective_policy")
    def test_restore_execution_gate_applies_to_execute_and_retry(
        self, effective_policy, tenant_get, schema_context, connection
    ):
        connection.schema_name = "demo"
        tenant_get.return_value = SimpleNamespace(schema_name="demo")
        schema_context.return_value.__enter__.return_value = None
        effective_policy.return_value = SimpleNamespace(restore_execution_allowed=False)
        permission = TenantBackupCapabilityPermission()
        self.assertFalse(permission.has_permission(self._request(), self._view("execute")))
        self.assertFalse(permission.has_permission(self._request(), self._view("retry")))

    @patch("backups.policy_permissions.connection")
    @patch("backups.policy_permissions.schema_context")
    @patch("backups.policy_permissions.Tenant.objects.get")
    @patch("backups.policy_permissions.effective_policy")
    def test_paused_tenant_denies_all_tenant_backup_actions(
        self, effective_policy, tenant_get, schema_context, connection
    ):
        connection.schema_name = "demo"
        tenant_get.return_value = SimpleNamespace(schema_name="demo")
        schema_context.return_value.__enter__.return_value = None
        effective_policy.return_value = SimpleNamespace(
            backups_enabled=False,
            manual_backups_allowed=True,
            restore_requests_allowed=True,
            restore_execution_allowed=True,
        )
        for action in ("create", "request_restore", "execute", "retry"):
            permission = TenantBackupCapabilityPermission()
            self.assertFalse(permission.has_permission(self._request(), self._view(action)))
            self.assertIn("paused", permission.message)

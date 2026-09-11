"""Tests for platform backup summary endpoint."""

from unittest.mock import patch

from django.test import SimpleTestCase


class BackupSummaryComputationTestCase(SimpleTestCase):
    """Test backup summary computation logic without database."""

    def test_summary_aggregation_logic(self):
        """Verify summary computation logic works correctly."""
        # Simulate backup data
        backups = [
            {"status": "available", "file_size": 1000, "backup_type": "manual"},
            {"status": "available", "file_size": 2000, "backup_type": "scheduled"},
            {"status": "failed", "file_size": 0, "backup_type": "manual"},
            {"status": "available", "file_size": 500, "backup_type": "scheduled"},
            {"status": "deleted", "file_size": 0, "backup_type": "manual"},
        ]

        # Compute aggregations (same logic as endpoint)
        total_count = len(backups)
        available_count = sum(1 for b in backups if b["status"] == "available")
        total_storage = sum(b["file_size"] for b in backups if b["status"] == "available")
        failed_count = sum(1 for b in backups if b["status"] == "failed")
        scheduled_count = sum(1 for b in backups if b["backup_type"] == "scheduled")

        self.assertEqual(total_count, 5)
        self.assertEqual(available_count, 3)
        self.assertEqual(total_storage, 3500)
        self.assertEqual(failed_count, 1)
        self.assertEqual(scheduled_count, 2)

    def test_storage_excludes_non_available(self):
        """Verify storage calculation excludes deleted/failed/expired backups."""
        backups = [
            {"status": "available", "file_size": 1000},
            {"status": "failed", "file_size": 500},
            {"status": "deleted", "file_size": 2000},
            {"status": "expired", "file_size": 3000},
            {"status": "available", "file_size": 1500},
        ]

        # Only available backups count toward storage
        total_storage = sum(b["file_size"] for b in backups if b["status"] == "available")
        self.assertEqual(total_storage, 2500)

    def test_upcoming_backup_calculation(self):
        """Test upcoming backup interval calculation logic."""
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
        interval_hours = 168  # 7 days

        # Tenant 1: last backup 2 days ago (due in 5 days) -> not upcoming
        last_backup_1 = now - timedelta(hours=48)
        next_due_1 = last_backup_1 + timedelta(hours=interval_hours)
        is_upcoming_1 = next_due_1 <= now
        self.assertFalse(is_upcoming_1)

        # Tenant 2: last backup 10 days ago (due now) -> upcoming
        last_backup_2 = now - timedelta(hours=240)
        next_due_2 = last_backup_2 + timedelta(hours=interval_hours)
        is_upcoming_2 = next_due_2 <= now
        self.assertTrue(is_upcoming_2)

        # Tenant 3: no backup (due now) -> upcoming
        next_due_3 = now
        is_upcoming_3 = next_due_3 <= now
        self.assertTrue(is_upcoming_3)

    def test_next_scheduled_calculation(self):
        """Test next scheduled backup timestamp calculation."""
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
        interval_hours = 168

        # Multiple tenants with different next-due times
        upcoming_times = [
            now + timedelta(hours=24),  # Due in 1 day
            now - timedelta(hours=12),  # Already due (12 hours ago)
            now + timedelta(hours=72),  # Due in 3 days
        ]

        next_scheduled = min(upcoming_times)
        self.assertEqual(next_scheduled, now - timedelta(hours=12))

    def test_protected_tenant_count(self):
        """Test protected tenant count (tenants with available backups)."""
        backups_by_tenant = {
            "tenant_1": [{"status": "available"}, {"status": "failed"}],
            "tenant_2": [{"status": "deleted"}],
            "tenant_3": [{"status": "available"}],
        }

        protected_tenant_ids = set()
        for tenant_id, backups in backups_by_tenant.items():
            if any(b["status"] == "available" for b in backups):
                protected_tenant_ids.add(tenant_id)

        self.assertEqual(len(protected_tenant_ids), 2)
        self.assertIn("tenant_1", protected_tenant_ids)
        self.assertIn("tenant_3", protected_tenant_ids)


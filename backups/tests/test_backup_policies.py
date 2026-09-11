from datetime import datetime, time, timezone as datetime_timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from backups.models import BackupPlatformSettings
from backups.policies import BackupPolicyError, calculate_next_run


class BackupPolicyScheduleTestCase(SimpleTestCase):
    def _policy(self, **overrides):
        values = {
            "timezone": "UTC",
            "scheduled_time": time(2, 0),
            "frequency": BackupPlatformSettings.Frequency.DAILY,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_daily_schedule_uses_configured_wall_clock(self):
        after = datetime(2026, 9, 11, 1, 0, tzinfo=datetime_timezone.utc)
        result = calculate_next_run(self._policy(), after=after)
        self.assertEqual(
            result,
            datetime(2026, 9, 11, 2, 0, tzinfo=datetime_timezone.utc),
        )

    def test_daily_schedule_rolls_to_next_day_after_time_passes(self):
        after = datetime(2026, 9, 11, 3, 0, tzinfo=datetime_timezone.utc)
        result = calculate_next_run(self._policy(), after=after)
        self.assertEqual(
            result,
            datetime(2026, 9, 12, 2, 0, tzinfo=datetime_timezone.utc),
        )

    def test_weekly_schedule_advances_seven_days(self):
        after = datetime(2026, 9, 11, 3, 0, tzinfo=datetime_timezone.utc)
        result = calculate_next_run(
            self._policy(frequency=BackupPlatformSettings.Frequency.WEEKLY),
            after=after,
        )
        self.assertEqual(
            result,
            datetime(2026, 9, 18, 2, 0, tzinfo=datetime_timezone.utc),
        )

    def test_schedule_respects_tenant_timezone(self):
        after = datetime(2026, 9, 11, 5, 0, tzinfo=datetime_timezone.utc)
        result = calculate_next_run(
            self._policy(timezone="America/Chicago", scheduled_time=time(2, 0)),
            after=after,
        )
        self.assertEqual(
            result,
            datetime(2026, 9, 11, 7, 0, tzinfo=datetime_timezone.utc),
        )

    def test_invalid_timezone_is_rejected(self):
        with self.assertRaises(BackupPolicyError):
            calculate_next_run(self._policy(timezone="Not/A-Timezone"))

"""Tests for the schooling-days breakdown used for academic-year planning."""

from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from academics.services.school_days import summarize_schooling_days


class SummarizeSchoolingDaysTests(SimpleTestCase):
    def _summarize(self, start, end, blocked=frozenset(), operating={1, 2, 3, 4, 5}):
        with patch(
            "academics.services.school_days.get_operating_days", return_value=set(operating)
        ), patch(
            "academics.services.school_days.get_blocked_days", return_value=set(blocked)
        ):
            return summarize_schooling_days(start, end)

    def test_counts_weekdays_and_flags_missing_holiday_data(self):
        summary = self._summarize(date(2025, 1, 6), date(2025, 1, 12))

        self.assertEqual(summary["weekdays"], 5)
        self.assertEqual(summary["holidays"], 0)
        self.assertEqual(summary["schooling_days"], 5)
        self.assertFalse(summary["holidays_configured"])

    def test_subtracts_holidays_that_fall_on_operating_days(self):
        summary = self._summarize(
            date(2025, 1, 6), date(2025, 1, 12), blocked={date(2025, 1, 8)}
        )

        self.assertEqual(summary["weekdays"], 5)
        self.assertEqual(summary["holidays"], 1)
        self.assertEqual(summary["schooling_days"], 4)
        self.assertTrue(summary["holidays_configured"])

    def test_holiday_on_a_weekend_is_not_subtracted_twice(self):
        summary = self._summarize(
            date(2025, 1, 6), date(2025, 1, 12), blocked={date(2025, 1, 11)}
        )

        self.assertEqual(summary["weekdays"], 5)
        self.assertEqual(summary["holidays"], 0)
        self.assertEqual(summary["schooling_days"], 5)

    def test_holidays_outside_the_range_are_ignored(self):
        summary = self._summarize(
            date(2025, 1, 6), date(2025, 1, 10), blocked={date(2025, 2, 3)}
        )

        self.assertEqual(summary["holidays"], 0)
        self.assertEqual(summary["schooling_days"], 5)

    def test_full_academic_year_breakdown(self):
        summary = self._summarize(date(2026, 9, 7), date(2027, 7, 22))

        self.assertEqual(
            summary["schooling_days"], summary["weekdays"] - summary["holidays"]
        )
        self.assertGreater(summary["weekdays"], 200)

    def test_inverted_range_returns_zeros(self):
        summary = self._summarize(date(2025, 2, 1), date(2025, 1, 1))

        self.assertEqual(summary["weekdays"], 0)
        self.assertEqual(summary["schooling_days"], 0)

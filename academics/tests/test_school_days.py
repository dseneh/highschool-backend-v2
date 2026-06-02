"""Tests for instructional school day counting."""

from datetime import date

from django.test import SimpleTestCase

from academics.services.school_days import count_instructional_days, iter_instructional_days


class SchoolDaysUtilityTests(SimpleTestCase):
    def test_counts_operating_days_excluding_weekends(self):
        total = count_instructional_days(
            date(2025, 1, 6),
            date(2025, 1, 12),
            operating_days={1, 2, 3, 4, 5},
            blocked_days=set(),
        )
        self.assertEqual(total, 5)

    def test_excludes_blocked_days(self):
        days = list(
            iter_instructional_days(
                date(2025, 1, 6),
                date(2025, 1, 10),
                operating_days={1, 2, 3, 4, 5},
                blocked_days={date(2025, 1, 8)},
            )
        )
        self.assertEqual(
            days,
            [
                date(2025, 1, 6),
                date(2025, 1, 7),
                date(2025, 1, 9),
                date(2025, 1, 10),
            ],
        )

    def test_returns_zero_for_invalid_range(self):
        self.assertEqual(
            count_instructional_days(
                date(2025, 2, 1),
                date(2025, 1, 1),
                operating_days={1, 2, 3, 4, 5},
                blocked_days=set(),
            ),
            0,
        )

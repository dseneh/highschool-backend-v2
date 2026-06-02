"""Tests for school calendar recurrence expansion."""

from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from academics.services.calendar_recurrence import (
    get_effective_recurrence_pattern,
    iter_event_occurrence_dates,
    resolve_recurrence_until,
)


def make_event(**kwargs):
    defaults = {
        "start_date": date(2025, 1, 6),
        "end_date": date(2025, 1, 6),
        "recurrence_pattern": "none",
        "recurrence_type": "none",
        "recurrence_interval": 1,
        "recurrence_until": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class CalendarRecurrenceTests(SimpleTestCase):
    def test_yearly_anchor_outside_academic_year_generates_occurrences(self):
        event = make_event(
            start_date=date(2025, 7, 4),
            end_date=date(2025, 7, 4),
            recurrence_pattern="yearly",
            recurrence_until=date(2027, 7, 4),
        )
        dates = list(
            iter_event_occurrence_dates(
                event,
                range_start=date(2026, 7, 1),
                range_end=date(2026, 7, 31),
            )
        )
        self.assertEqual(dates, [date(2026, 7, 4)])

    def test_weekly_occurrences(self):
        event = make_event(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 1, 6),
            recurrence_pattern="weekly",
            recurrence_interval=1,
            recurrence_until=date(2025, 1, 27),
        )
        self.assertEqual(
            list(iter_event_occurrence_dates(event)),
            [
                date(2025, 1, 6),
                date(2025, 1, 13),
                date(2025, 1, 20),
                date(2025, 1, 27),
            ],
        )

    def test_biweekly_occurrences(self):
        event = make_event(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 1, 6),
            recurrence_pattern="weekly",
            recurrence_interval=2,
            recurrence_until=date(2025, 2, 3),
        )
        self.assertEqual(
            list(iter_event_occurrence_dates(event)),
            [date(2025, 1, 6), date(2025, 1, 20), date(2025, 2, 3)],
        )

    def test_monthly_day_occurrences(self):
        event = make_event(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            recurrence_pattern="monthly_day",
            recurrence_until=date(2025, 3, 1),
        )
        self.assertEqual(
            list(iter_event_occurrence_dates(event)),
            [date(2025, 1, 1), date(2025, 2, 1), date(2025, 3, 1)],
        )

    def test_monthly_first_weekday_occurrences(self):
        event = make_event(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 1, 6),
            recurrence_pattern="monthly_first_weekday",
            recurrence_until=date(2025, 3, 31),
        )
        self.assertEqual(
            list(iter_event_occurrence_dates(event)),
            [date(2025, 1, 6), date(2025, 2, 3), date(2025, 3, 3)],
        )

    def test_monthly_last_weekday_occurrences(self):
        event = make_event(
            start_date=date(2025, 1, 27),
            end_date=date(2025, 1, 27),
            recurrence_pattern="monthly_last_weekday",
            recurrence_until=date(2025, 3, 31),
        )
        self.assertEqual(
            list(iter_event_occurrence_dates(event)),
            [date(2025, 1, 27), date(2025, 2, 24), date(2025, 3, 31)],
        )

    def test_default_recurrence_until_without_academic_year(self):
        event = make_event(start_date=date(2025, 1, 6))
        resolved = resolve_recurrence_until(event, academic_year=None)
        self.assertEqual(resolved, date(2030, 1, 6))

    def test_legacy_recurrence_type_maps_to_yearly(self):
        event = make_event(recurrence_pattern="none", recurrence_type="yearly")
        self.assertEqual(get_effective_recurrence_pattern(event), "yearly")

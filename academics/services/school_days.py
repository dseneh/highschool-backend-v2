"""Instructional school day counting utilities."""

from __future__ import annotations

from datetime import date
from typing import Iterable, Optional, Set

from academics.models import SchoolCalendarEvent, SchoolCalendarEventOccurrence, SchoolCalendarSettings


def get_operating_days() -> Set[int]:
    settings = SchoolCalendarSettings.get_solo()
    return set(settings.operating_days or [1, 2, 3, 4, 5])


def get_blocked_days(start: date, end: date) -> Set[date]:
    return set(
        SchoolCalendarEventOccurrence.objects.filter(
            occurrence_date__gte=start,
            occurrence_date__lte=end,
            event__event_type__in=[
                SchoolCalendarEvent.EventType.HOLIDAY,
                SchoolCalendarEvent.EventType.NON_SCHOOL_DAY,
            ],
            event__active=True,
        )
        .values_list("occurrence_date", flat=True)
        .distinct()
    )


def iter_instructional_days(
    start: date,
    end: date,
    *,
    operating_days: Optional[Set[int]] = None,
    blocked_days: Optional[Set[date]] = None,
) -> Iterable[date]:
    if start > end:
        return

    operating = operating_days if operating_days is not None else get_operating_days()
    blocked = blocked_days if blocked_days is not None else get_blocked_days(start, end)

    current = start
    while current <= end:
        if current.isoweekday() in operating and current not in blocked:
            yield current
        current = current.fromordinal(current.toordinal() + 1)


def count_instructional_days(
    start: date,
    end: date,
    *,
    operating_days: Optional[Set[int]] = None,
    blocked_days: Optional[Set[date]] = None,
) -> int:
    return sum(
        1
        for _ in iter_instructional_days(
            start,
            end,
            operating_days=operating_days,
            blocked_days=blocked_days,
        )
    )


def count_instructional_days_for_year(
    academic_year,
    *,
    end_cap: Optional[date] = None,
) -> int:
    if not academic_year:
        return 0

    period_end = academic_year.end_date
    if end_cap is not None:
        period_end = min(period_end, end_cap)

    if academic_year.start_date > period_end:
        return 0

    return count_instructional_days(academic_year.start_date, period_end)


def get_academic_year_duration(academic_year) -> dict:
    """Instructional progress for an academic year (school days, not calendar days)."""
    today = date.today()
    total_days = count_instructional_days_for_year(academic_year)
    days_elapsed = count_instructional_days_for_year(academic_year, end_cap=today)
    completion_percentage = int((days_elapsed / total_days * 100)) if total_days > 0 else 0
    return {
        "total_days": total_days,
        "days_elapsed": days_elapsed,
        "completion_percentage": completion_percentage,
    }

"""Expand school calendar event recurrence into concrete occurrence dates."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Iterable, Optional

from academics.models import AcademicYear

RECURRENCE_PATTERNS = frozenset(
    {
        "none",
        "yearly",
        "weekly",
        "monthly_day",
        "monthly_first_weekday",
        "monthly_last_weekday",
    }
)

DEFAULT_RECURRENCE_HORIZON_YEARS = 5

_UNSET = object()


def get_effective_recurrence_pattern(event) -> str:
    pattern = getattr(event, "recurrence_pattern", None) or ""
    if pattern in RECURRENCE_PATTERNS and pattern != "none":
        return pattern

    recurrence_type = getattr(event, "recurrence_type", "none")
    if recurrence_type == "yearly":
        return "yearly"
    return "none"


def resolve_recurrence_until(event, *, academic_year=_UNSET) -> date:
    explicit_until = getattr(event, "recurrence_until", None)
    if explicit_until:
        return explicit_until

    if academic_year is _UNSET:
        academic_year = AcademicYear.get_current_academic_year()

    if academic_year:
        return academic_year.end_date

    fallback_year = event.start_date.year + DEFAULT_RECURRENCE_HORIZON_YEARS
    try:
        return event.start_date.replace(year=fallback_year)
    except ValueError:
        if event.start_date.month == 2 and event.start_date.day == 29:
            return event.start_date.replace(year=fallback_year, day=28)
        raise


def normalize_date_to_year(source: date, year: int) -> date:
    try:
        return source.replace(year=year)
    except ValueError:
        if source.month == 2 and source.day == 29:
            return source.replace(year=year, day=28)
        raise


def _first_weekday_in_month(year: int, month: int, weekday: int) -> date:
    current = date(year, month, 1)
    while current.isoweekday() != weekday:
        current += timedelta(days=1)
    return current


def _last_weekday_in_month(year: int, month: int, weekday: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    current = date(year, month, last_day)
    while current.isoweekday() != weekday:
        current -= timedelta(days=1)
    return current


def _day_in_month(year: int, month: int, day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _emit_occurrence_span(
    occurrence_start: date,
    duration_days: int,
    *,
    series_until: date,
    range_start: Optional[date],
    range_end: Optional[date],
) -> Iterable[date]:
    occurrence_end = occurrence_start + timedelta(days=duration_days)
    if occurrence_start > series_until:
        return

    capped_end = min(occurrence_end, series_until)
    current = occurrence_start
    while current <= capped_end:
        if range_start and current < range_start:
            current += timedelta(days=1)
            continue
        if range_end and current > range_end:
            break
        yield current
        current += timedelta(days=1)


def _iter_yearly_occurrence_starts(event, series_until: date) -> Iterable[date]:
    start_year = event.start_date.year
    end_year = series_until.year
    for year in range(start_year, end_year + 1):
        occurrence_start = normalize_date_to_year(event.start_date, year)
        if occurrence_start <= series_until:
            yield occurrence_start


def _iter_weekly_occurrence_starts(event, series_until: date) -> Iterable[date]:
    interval = max(1, int(getattr(event, "recurrence_interval", None) or 1))
    current = event.start_date
    while current <= series_until:
        yield current
        current += timedelta(weeks=interval)


def _iter_monthly_occurrence_starts(event, series_until: date) -> Iterable[date]:
    pattern = get_effective_recurrence_pattern(event)
    weekday = event.start_date.isoweekday()
    day_of_month = event.start_date.day

    year = event.start_date.year
    month = event.start_date.month

    while True:
        if pattern == "monthly_day":
            occurrence_start = _day_in_month(year, month, day_of_month)
        elif pattern == "monthly_first_weekday":
            occurrence_start = _first_weekday_in_month(year, month, weekday)
        else:
            occurrence_start = _last_weekday_in_month(year, month, weekday)

        if occurrence_start >= event.start_date and occurrence_start <= series_until:
            yield occurrence_start

        if year > series_until.year or (year == series_until.year and month >= series_until.month):
            break

        month += 1
        if month > 12:
            month = 1
            year += 1


def iter_event_occurrence_dates(
    event,
    *,
    range_start: Optional[date] = None,
    range_end: Optional[date] = None,
    academic_year=None,
) -> Iterable[date]:
    """Yield unique occurrence dates for an event, optionally clipped to a range."""
    pattern = get_effective_recurrence_pattern(event)
    duration_days = max(0, (event.end_date - event.start_date).days)

    if pattern == "none":
        for current in _emit_occurrence_span(
            event.start_date,
            duration_days,
            series_until=event.end_date,
            range_start=range_start,
            range_end=range_end,
        ):
            yield current
        return

    series_until = resolve_recurrence_until(event, academic_year=academic_year)

    if pattern == "yearly":
        occurrence_starts = _iter_yearly_occurrence_starts(event, series_until)
    elif pattern == "weekly":
        occurrence_starts = _iter_weekly_occurrence_starts(event, series_until)
    elif pattern in {"monthly_day", "monthly_first_weekday", "monthly_last_weekday"}:
        occurrence_starts = _iter_monthly_occurrence_starts(event, series_until)
    else:
        return

    seen: set[date] = set()
    for occurrence_start in occurrence_starts:
        for occurrence_date in _emit_occurrence_span(
            occurrence_start,
            duration_days,
            series_until=series_until,
            range_start=range_start,
            range_end=range_end,
        ):
            if occurrence_date not in seen:
                seen.add(occurrence_date)
                yield occurrence_date


def sync_legacy_recurrence_type(event) -> None:
    """Keep recurrence_type aligned with recurrence_pattern for legacy consumers."""
    pattern = get_effective_recurrence_pattern(event)
    event.recurrence_type = "yearly" if pattern == "yearly" else "none"

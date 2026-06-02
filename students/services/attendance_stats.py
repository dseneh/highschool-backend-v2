"""Shared attendance counting helpers (reports, student profile, roster)."""

from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from academics.services.school_days import count_instructional_days
from common.status import AttendanceStatus


ABSENCE_STATUS_VALUES = frozenset(
    {
        AttendanceStatus.ABSENT.value,
        AttendanceStatus.LATE.value,
        AttendanceStatus.EXCUSED.value,
        AttendanceStatus.SICK.value,
        AttendanceStatus.ON_LEAVE.value,
        AttendanceStatus.HOLIDAY.value,
    }
)


def count_school_days(
    academic_year,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> int:
    """Count instructional days in range (defaults: year start through today)."""
    if not academic_year:
        return 0

    today = date.today()
    period_start = max(start_date or academic_year.start_date, academic_year.start_date)
    period_end = min(
        end_date or academic_year.end_date,
        academic_year.end_date,
        today,
    )

    return count_instructional_days(period_start, period_end)


def build_student_attendance_summary(attendance_rows: Iterable, school_days_elapsed: int) -> dict:
    """
    Summarize attendance for a student over ``school_days_elapsed`` days.
    Days without a recorded absence count as present (unmarked = present).
    """
    status_counts: dict[str, int] = {}

    recorded_absences = 0
    for row in attendance_rows:
        raw_status = getattr(row, "status", row.get("status") if isinstance(row, dict) else None)
        status_key = str(raw_status or "").strip().lower()
        if not status_key:
            continue
        status_counts[status_key] = status_counts.get(status_key, 0) + 1
        if status_key in ABSENCE_STATUS_VALUES:
            recorded_absences += 1

    implied_present_days = max(school_days_elapsed - recorded_absences, 0)
    attendance_rate = (
        round((implied_present_days / school_days_elapsed) * 100, 2) if school_days_elapsed else 0
    )

    return {
        "school_days_elapsed": school_days_elapsed,
        "recorded_absences": recorded_absences,
        "present_days": implied_present_days,
        "attendance_rate": attendance_rate,
        "status_counts": status_counts,
        "present": status_counts.get(AttendanceStatus.PRESENT.value, 0),
        "absent": status_counts.get(AttendanceStatus.ABSENT.value, 0),
        "late": status_counts.get(AttendanceStatus.LATE.value, 0),
        "excused": status_counts.get(AttendanceStatus.EXCUSED.value, 0),
        "sick": status_counts.get(AttendanceStatus.SICK.value, 0),
        "on_leave": status_counts.get(AttendanceStatus.ON_LEAVE.value, 0),
        "holiday": status_counts.get(AttendanceStatus.HOLIDAY.value, 0),
    }

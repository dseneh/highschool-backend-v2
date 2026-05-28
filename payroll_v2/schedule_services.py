"""Pay schedule period derivation for payroll v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .enums import PayScheduleFrequency
from .models import PaySchedule, PayrollPeriod


def get_pay_schedule(schedule_id):
    """Return a pay schedule by id without raising DoesNotExist."""
    if not schedule_id:
        return None
    return PaySchedule.objects.select_related("currency").filter(id=schedule_id).first()


def get_employee_pay_schedule(employee):
    """Return an employee's pay schedule, tolerating stale FK ids."""
    if employee is None:
        return None
    schedule_id = getattr(employee, "pay_schedule_id", None)
    if not schedule_id:
        return None
    return get_pay_schedule(schedule_id)


@dataclass
class DerivedPeriod:
    name: str
    start_date: date
    end_date: date
    payment_date: date


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last_day = (date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def _format_period_name(schedule: PaySchedule, start: date, end: date) -> str:
    if schedule.frequency == PayScheduleFrequency.MONTHLY:
        return f"{schedule.name} – {start.strftime('%b %Y')}"
    return f"{schedule.name} – {start.strftime('%b %d')} to {end.strftime('%b %d, %Y')}"


def derive_next_period(schedule: PaySchedule) -> DerivedPeriod:
    last = (
        PayrollPeriod.objects.filter(schedule=schedule)
        .order_by("-end_date")
        .first()
    )

    if last:
        cursor_start = last.end_date + timedelta(days=1)
    else:
        cursor_start = schedule.anchor_date

    if schedule.frequency == PayScheduleFrequency.MONTHLY:
        end = _add_months(cursor_start, 1) - timedelta(days=1)
    elif schedule.frequency == PayScheduleFrequency.BIWEEKLY:
        end = cursor_start + timedelta(days=13)
    else:
        end = cursor_start + timedelta(days=6)

    payment_date = end + timedelta(days=schedule.payment_day_offset or 0)

    return DerivedPeriod(
        name=_format_period_name(schedule, cursor_start, end),
        start_date=cursor_start,
        end_date=end,
        payment_date=payment_date,
    )


def periods_per_year_for_schedule(schedule) -> Decimal:
    if schedule is None:
        return Decimal("12")
    frequency = getattr(schedule, "frequency", None) or PayScheduleFrequency.MONTHLY
    if frequency == PayScheduleFrequency.WEEKLY:
        return Decimal("52")
    if frequency == PayScheduleFrequency.BIWEEKLY:
        return Decimal("26")
    return Decimal("12")


def annual_salary_from_period_basic(
    basic: Decimal,
    *,
    periods_per_year: Decimal | None = None,
) -> Decimal:
    pp = periods_per_year or Decimal("12")
    return Decimal(basic or 0) * pp

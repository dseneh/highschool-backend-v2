from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from uuid import UUID

from dateutil.relativedelta import relativedelta
from django.db.models import Count, Max, Min, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounting.models import (
    AccountingBankAccount,
    AccountingJournalEntry,
    AccountingJournalLine,
)


def _ledger_account_ids_for_bank_param(bank_account: str | None) -> list:
    """Resolve bank filter param to linked GL cash account ids."""
    bank_account_value = (bank_account or "").strip()
    if not bank_account_value:
        return list(
            AccountingBankAccount.objects.exclude(ledger_account_id__isnull=True)
            .values_list("ledger_account_id", flat=True)
            .distinct()
        )

    account_filter = Q(account_number__iexact=bank_account_value)
    try:
        UUID(bank_account_value)
    except (ValueError, AttributeError, TypeError):
        return list(
            AccountingBankAccount.objects.filter(account_filter)
            .exclude(ledger_account_id__isnull=True)
            .values_list("ledger_account_id", flat=True)
            .distinct()
        )

    account_filter |= Q(id=bank_account_value)
    return list(
        AccountingBankAccount.objects.filter(account_filter)
        .exclude(ledger_account_id__isnull=True)
        .values_list("ledger_account_id", flat=True)
        .distinct()
    )


def _parse_filter_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _month_end(year: int, month: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def compute_posted_ledger_balance(
    ledger_account_ids: list,
    *,
    end_date=None,
) -> Decimal:
    """Cash/bank balance from posted journal lines (debits − credits)."""
    if not ledger_account_ids:
        return Decimal("0")

    lines = AccountingJournalLine.objects.filter(
        journal_entry__status=AccountingJournalEntry.EntryStatus.POSTED,
        ledger_account_id__in=ledger_account_ids,
    )
    if end_date:
        lines = lines.filter(journal_entry__posting_date__lte=end_date)

    totals = lines.aggregate(
        total_debit=Coalesce(Sum("debit_amount"), Value(Decimal("0"))),
        total_credit=Coalesce(Sum("credit_amount"), Value(Decimal("0"))),
    )
    debit = totals["total_debit"] or Decimal("0")
    credit = totals["total_credit"] or Decimal("0")
    return debit - credit


def _compute_metric_trend(current: Decimal, previous: Decimal | None) -> dict | None:
    if previous is None:
        return None

    if previous == 0:
        if current == 0:
            return {"pct": 0.0, "direction": "neutral", "previous": "0.00"}
        return {
            "pct": 100.0,
            "direction": "up" if current > 0 else "neutral",
            "previous": "0.00",
        }

    pct_change = ((current - previous) / abs(previous)) * 100
    if abs(pct_change) < 0.05:
        direction = "neutral"
    elif pct_change > 0:
        direction = "up"
    else:
        direction = "down"

    return {
        "pct": round(abs(float(pct_change)), 1),
        "direction": direction,
        "previous": str(round(previous, 2)),
    }


def compute_balance_month_over_month_trend(
    ledger_account_ids: list,
    *,
    as_of: date | None = None,
) -> dict | None:
    anchor = as_of or timezone.localdate()
    current_balance = compute_posted_ledger_balance(ledger_account_ids, end_date=anchor)
    prior_month_end = _month_end(anchor.year, anchor.month) - relativedelta(months=1)
    prior_balance = compute_posted_ledger_balance(ledger_account_ids, end_date=prior_month_end)

    trend = _compute_metric_trend(current_balance, prior_balance)
    if trend is None:
        return None

    trend["previous_month_label"] = prior_month_end.strftime("%b %Y")
    return trend


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _iter_calendar_months(start: date, end: date):
    """Yield the first day of each calendar month from start through end."""
    cursor = _month_start(start)
    last = _month_start(end)
    while cursor <= last:
        yield cursor
        cursor = cursor + relativedelta(months=1)


def _first_posted_ledger_activity_month(
    ledger_account_ids: list,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> date | None:
    if not ledger_account_ids:
        return None

    lines = AccountingJournalLine.objects.filter(
        journal_entry__status=AccountingJournalEntry.EntryStatus.POSTED,
        ledger_account_id__in=ledger_account_ids,
    )
    if start_date:
        lines = lines.filter(journal_entry__posting_date__gte=start_date)
    if end_date:
        lines = lines.filter(journal_entry__posting_date__lte=end_date)

    first_posting_date = lines.order_by("journal_entry__posting_date").values_list(
        "journal_entry__posting_date",
        flat=True,
    ).first()
    if not first_posting_date:
        return None
    return _month_start(first_posting_date)


def _queryset_posting_bounds(queryset) -> tuple[date | None, date | None]:
    if queryset is None:
        return None, None
    bounds = queryset.exclude(posting_date__isnull=True).aggregate(
        min_date=Min("posting_date"),
        max_date=Max("posting_date"),
    )
    return bounds["min_date"], bounds["max_date"]


def build_monthly_ledger_balance_series(
    ledger_account_ids: list,
    *,
    queryset=None,
    as_of: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, str]]:
    """One balance point per calendar month from first activity through range end."""
    if not ledger_account_ids:
        return []

    filter_min, filter_max = _queryset_posting_bounds(queryset)
    ledger_activity_start = _first_posted_ledger_activity_month(
        ledger_account_ids,
        start_date=start_date,
        end_date=end_date,
    )

    if filter_min is None and ledger_activity_start is None:
        return []

    activity_start = _month_start(filter_min) if filter_min else ledger_activity_start
    if ledger_activity_start and activity_start:
        activity_start = min(activity_start, ledger_activity_start)
    elif ledger_activity_start:
        activity_start = ledger_activity_start

    series_end = end_date or as_of or timezone.localdate()
    if filter_max and not end_date:
        series_end = max(series_end, filter_max)

    if start_date:
        requested_start = _month_start(start_date)
        series_start = max(requested_start, activity_start)
    else:
        series_start = activity_start

    if series_start > series_end:
        return []

    spans_multiple_years = series_start.year != series_end.year
    points: list[dict[str, str]] = []

    for month_start in _iter_calendar_months(series_start, series_end):
        period_end = _month_end(month_start.year, month_start.month)
        if period_end > series_end:
            period_end = series_end

        balance = compute_posted_ledger_balance(ledger_account_ids, end_date=period_end)
        short_label = (
            month_start.strftime("%b '%y")
            if spans_multiple_years
            else month_start.strftime("%b")
        )
        points.append(
            {
                "month": month_start.strftime("%Y-%m"),
                "label": period_end.strftime("%b %Y"),
                "short_label": short_label,
                "balance": str(balance),
            }
        )

    return points


def build_journal_entry_list_summary(queryset, params=None) -> dict[str, object]:
    """Aggregate journal-entry list stats across the full filtered queryset."""
    params = params or {}
    posted_status = AccountingJournalEntry.EntryStatus.POSTED

    entry_counts = queryset.aggregate(
        total_count=Count("id"),
        posted_count=Count("id", filter=Q(status=posted_status)),
        draft_count=Count("id", filter=Q(status=AccountingJournalEntry.EntryStatus.DRAFT)),
        reversed_count=Count("id", filter=Q(status=AccountingJournalEntry.EntryStatus.REVERSED)),
    )

    bank_account = params.get("bank_account")
    end_date = _parse_filter_date(params.get("end_date"))
    start_date = _parse_filter_date(params.get("start_date"))
    as_of = end_date or timezone.localdate()

    ledger_account_ids = _ledger_account_ids_for_bank_param(
        str(bank_account).strip() if bank_account else None
    )
    ledger_balance = compute_posted_ledger_balance(
        ledger_account_ids,
        end_date=as_of,
    )

    balance_scope = "bank_account" if (bank_account and str(bank_account).strip()) else "all_cash_accounts"
    balance_trend = compute_balance_month_over_month_trend(
        ledger_account_ids,
        as_of=as_of,
    )
    monthly_ledger_balance = build_monthly_ledger_balance_series(
        ledger_account_ids,
        queryset=queryset,
        as_of=as_of,
        start_date=start_date,
        end_date=end_date,
    )

    return {
        "total_count": entry_counts["total_count"] or 0,
        "posted_count": entry_counts["posted_count"] or 0,
        "draft_count": entry_counts["draft_count"] or 0,
        "reversed_count": entry_counts["reversed_count"] or 0,
        "posted_ledger_balance": str(ledger_balance),
        "balance_scope": balance_scope,
        "posted_ledger_balance_trend": balance_trend,
        "monthly_ledger_balance": monthly_ledger_balance,
    }

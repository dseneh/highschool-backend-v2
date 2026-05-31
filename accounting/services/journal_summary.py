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
    AccountingCashTransaction,
    AccountingJournalEntry,
    AccountingJournalLine,
)
from accounting.services.currency_totals import (
    approved_signed_base_amount_expression,
    approved_signed_native_amount_expression,
    compute_posted_ledger_balance_base,
    compute_posted_ledger_balance_native,
    convert_amount_to_base,
    get_tenant_base_currency,
    serialize_currency,
)


def _ledger_account_ids_for_bank_param(bank_account: str | None) -> list:
    """Resolve bank filter param to linked GL cash account ids."""
    return list(
        _bank_accounts_queryset(bank_account)
        .exclude(ledger_account_id__isnull=True)
        .values_list("ledger_account_id", flat=True)
        .distinct()
    )


def _bank_accounts_queryset(bank_account: str | None):
    """Bank/cash accounts included in balance stats."""
    bank_account_value = (bank_account or "").strip()
    queryset = AccountingBankAccount.objects.all()
    if not bank_account_value:
        return queryset

    account_filter = Q(account_number__iexact=bank_account_value)
    try:
        UUID(bank_account_value)
    except (ValueError, AttributeError, TypeError):
        return queryset.filter(account_filter)

    account_filter |= Q(id=bank_account_value)
    return queryset.filter(account_filter)


def _opening_balance_as_of(
    bank_account: AccountingBankAccount,
    *,
    end_date: date | None = None,
) -> Decimal:
    opening = bank_account.opening_balance or Decimal("0")
    if opening == 0:
        return Decimal("0")

    opening_date = bank_account.opening_balance_date
    if end_date and opening_date and opening_date > end_date:
        return Decimal("0")
    return opening


def _approved_cash_net_base(
    bank_account: AccountingBankAccount,
    *,
    end_date: date | None = None,
) -> Decimal:
    approved = bank_account.transactions.filter(
        status=AccountingCashTransaction.TransactionStatus.APPROVED,
    )
    if end_date:
        approved = approved.filter(transaction_date__lte=end_date)

    signed_amount = approved_signed_base_amount_expression()
    total = approved.aggregate(net=Sum(signed_amount))["net"]
    return total or Decimal("0")


def _approved_cash_net_native(
    bank_account: AccountingBankAccount,
    *,
    end_date: date | None = None,
) -> Decimal:
    approved = bank_account.transactions.filter(
        status=AccountingCashTransaction.TransactionStatus.APPROVED,
    )
    if end_date:
        approved = approved.filter(transaction_date__lte=end_date)

    signed_amount = approved_signed_native_amount_expression()
    total = approved.aggregate(net=Sum(signed_amount))["net"]
    return total or Decimal("0")


def _ledger_gl_balance_base(
    bank_account: AccountingBankAccount,
    *,
    end_date: date | None = None,
) -> Decimal:
    """Net posted GL effect on a bank ledger (debits − credits) in base currency."""
    if not bank_account.ledger_account_id:
        return Decimal("0")
    return compute_posted_ledger_balance_base(
        [bank_account.ledger_account_id],
        end_date=end_date,
    )


def _ledger_gl_balance_native(
    bank_account: AccountingBankAccount,
    *,
    end_date: date | None = None,
) -> Decimal:
    """Net posted GL effect on a bank ledger (debits − credits) in native currency."""
    if not bank_account.ledger_account_id:
        return Decimal("0")
    return compute_posted_ledger_balance_native(
        [bank_account.ledger_account_id],
        end_date=end_date,
    )


def _account_cash_standing_base(
    bank_account: AccountingBankAccount,
    *,
    end_date: date | None = None,
) -> Decimal:
    """
    Cash standing for one bank account in tenant base currency.

    When a GL account is linked, the posted ledger balance (debits − credits on
    bank lines, using ``base_amount``) is authoritative. The ``opening_balance``
    field is not added on top — opening must be posted to the GL once.

    Without a linked GL, use opening balance plus signed approved cash
    transactions (``base_amount``).
    """
    if bank_account.ledger_account_id:
        return _ledger_gl_balance_base(bank_account, end_date=end_date)

    opening = _opening_balance_as_of(bank_account, end_date=end_date)
    opening_base = (
        convert_amount_to_base(
            opening,
            bank_account.currency,
            as_of=end_date or bank_account.opening_balance_date,
        )
        if opening
        else Decimal("0")
    )
    return opening_base + _approved_cash_net_base(bank_account, end_date=end_date)


def _account_cash_standing_native(
    bank_account: AccountingBankAccount,
    *,
    end_date: date | None = None,
) -> Decimal:
    """Cash standing for one bank account in the account's native currency."""
    if bank_account.ledger_account_id:
        return _ledger_gl_balance_native(bank_account, end_date=end_date)

    opening = _opening_balance_as_of(bank_account, end_date=end_date)
    return opening + _approved_cash_net_native(bank_account, end_date=end_date)


def _iter_unique_cash_standing_accounts(
    bank_account: str | None = None,
):
    """
    Yield bank accounts for cash-standing totals.

    Multiple bank/cash accounts may share one GL ledger (same currency). Count
    each linked ledger once so the GL net is not multiplied.
    """
    counted_ledger_ids = set()
    for account in _bank_accounts_queryset(bank_account).select_related("currency"):
        ledger_id = account.ledger_account_id
        if ledger_id:
            if ledger_id in counted_ledger_ids:
                continue
            counted_ledger_ids.add(ledger_id)
        yield account


def compute_approved_cash_net_total(
    bank_account: str | None = None,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Decimal:
    """
    Net approved cash transactions in base currency — same basis as the
    Cash Transactions page ``approved_net_total`` summary.
    """
    from accounting.models import AccountingCashTransaction
    from accounting.services.post_all import (
        apply_cash_transaction_list_filters,
        build_cash_transaction_list_summary,
    )

    filter_params: dict[str, str] = {}
    if bank_account:
        filter_params["bank_account"] = bank_account
    if start_date:
        filter_params["start_date"] = start_date.isoformat()
    if end_date:
        filter_params["end_date"] = end_date.isoformat()

    queryset = AccountingCashTransaction.objects.all()
    queryset = apply_cash_transaction_list_filters(queryset, filter_params)
    summary = build_cash_transaction_list_summary(queryset)
    return Decimal(str(summary["approved_net_total"]))


def compute_cash_standing_balance(
    bank_account: str | None = None,
    *,
    end_date: date | None = None,
) -> Decimal:
    """Cash on hand consolidated in tenant base currency."""
    total = Decimal("0")
    for account in _iter_unique_cash_standing_accounts(bank_account):
        total += _account_cash_standing_base(account, end_date=end_date)
    return total


def compute_cash_standing_by_currency(
    bank_account: str | None = None,
    *,
    end_date: date | None = None,
) -> list[dict[str, str]]:
    """Cash on hand grouped by each bank account's native currency."""
    buckets: dict[str, dict[str, object]] = {}

    for account in _iter_unique_cash_standing_accounts(bank_account):
        code = account.currency.code if account.currency else "—"
        symbol = account.currency.symbol if account.currency else code
        bucket = buckets.setdefault(
            code,
            {"currency_code": code, "currency_symbol": str(symbol), "balance": Decimal("0")},
        )
        bucket["balance"] = (bucket["balance"] or Decimal("0")) + _account_cash_standing_native(
            account,
            end_date=end_date,
        )

    return [
        {
            "currency_code": str(item["currency_code"]),
            "currency_symbol": str(item["currency_symbol"]),
            "balance": str(item["balance"] or Decimal("0")),
        }
        for item in sorted(buckets.values(), key=lambda row: str(row["currency_code"]))
    ]


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
    """Posted GL balance in tenant base currency."""
    return compute_posted_ledger_balance_base(ledger_account_ids, end_date=end_date)


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
    bank_account: str | None = None,
    *,
    as_of: date | None = None,
) -> dict | None:
    anchor = as_of or timezone.localdate()
    current_balance = compute_cash_standing_balance(bank_account, end_date=anchor)
    prior_month_end = _month_end(anchor.year, anchor.month) - relativedelta(months=1)
    prior_balance = compute_cash_standing_balance(bank_account, end_date=prior_month_end)

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


def _first_approved_cash_activity_month(
    accounts: list[AccountingBankAccount],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> date | None:
    account_ids = [account.id for account in accounts]
    if not account_ids:
        return None

    transactions = AccountingCashTransaction.objects.filter(
        bank_account_id__in=account_ids,
        status=AccountingCashTransaction.TransactionStatus.APPROVED,
    )
    if start_date:
        transactions = transactions.filter(transaction_date__gte=start_date)
    if end_date:
        transactions = transactions.filter(transaction_date__lte=end_date)

    first_date = transactions.order_by("transaction_date").values_list(
        "transaction_date",
        flat=True,
    ).first()
    if not first_date:
        return None
    return _month_start(first_date)


def _resolve_activity_start_month(
    accounts: list[AccountingBankAccount],
    ledger_account_ids: list,
    *,
    queryset=None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> date | None:
    candidates: list[date] = []

    filter_min, _ = _queryset_posting_bounds(queryset)
    if filter_min:
        candidates.append(_month_start(filter_min))

    if ledger_account_ids:
        ledger_start = _first_posted_ledger_activity_month(
            ledger_account_ids,
            start_date=start_date,
            end_date=end_date,
        )
        if ledger_start:
            candidates.append(ledger_start)

    cash_start = _first_approved_cash_activity_month(
        accounts,
        start_date=start_date,
        end_date=end_date,
    )
    if cash_start:
        candidates.append(cash_start)

    for account in accounts:
        if not account.opening_balance:
            continue
        opening_date = account.opening_balance_date or date(1900, 1, 1)
        if end_date and opening_date > end_date:
            continue
        if start_date and opening_date < start_date:
            candidates.append(_month_start(start_date))
        else:
            candidates.append(_month_start(opening_date))

    if not candidates:
        return None
    return min(candidates)


def build_monthly_ledger_balance_series(
    bank_account: str | None = None,
    *,
    queryset=None,
    as_of: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, str]]:
    """One cash-standing point per calendar month from first activity through range end."""
    accounts = list(_bank_accounts_queryset(bank_account))
    if not accounts:
        return []

    bank_account_param = (bank_account or "").strip() or None
    ledger_account_ids = [
        account.ledger_account_id
        for account in accounts
        if account.ledger_account_id
    ]

    series_end = end_date or as_of or timezone.localdate()
    _, filter_max = _queryset_posting_bounds(queryset)
    if filter_max and not end_date:
        series_end = max(series_end, filter_max)

    activity_start = _resolve_activity_start_month(
        accounts,
        ledger_account_ids,
        queryset=queryset,
        start_date=start_date,
        end_date=end_date,
    )
    if activity_start is None:
        return []

    if start_date:
        series_start = max(_month_start(start_date), activity_start)
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

        balance = compute_cash_standing_balance(bank_account_param, end_date=period_end)
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

    bank_account_param = str(bank_account).strip() if bank_account else None
    cash_balance = compute_cash_standing_balance(bank_account_param, end_date=as_of)
    cash_by_currency = compute_cash_standing_by_currency(bank_account_param, end_date=as_of)
    approved_cash_net = compute_approved_cash_net_total(
        bank_account_param,
        start_date=start_date,
        end_date=end_date,
    )
    base_currency = serialize_currency(get_tenant_base_currency())

    balance_scope = "bank_account" if bank_account_param else "all_cash_accounts"
    balance_trend = compute_balance_month_over_month_trend(
        bank_account_param,
        as_of=as_of,
    )
    monthly_ledger_balance = build_monthly_ledger_balance_series(
        bank_account_param,
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
        "posted_ledger_balance": str(cash_balance),
        "approved_cash_net_total": str(approved_cash_net),
        "base_currency": base_currency,
        "cash_balances_by_currency": cash_by_currency,
        "balance_scope": balance_scope,
        "posted_ledger_balance_trend": balance_trend,
        "monthly_ledger_balance": monthly_ledger_balance,
    }

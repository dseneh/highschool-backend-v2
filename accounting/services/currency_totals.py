"""Multi-currency helpers for balances and report totals."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Case, DecimalField, F, Q, QuerySet, Sum, Value, When
from django.db.models.functions import Abs, Coalesce

from accounting.models import (
    AccountingCurrency,
    AccountingExchangeRate,
    AccountingJournalEntry,
    AccountingJournalLine,
)
from accounting.services.posting import _inflow_filter, _outflow_filter

INCOME_CATEGORY = Q(transaction_type__transaction_category="income")
EXPENSE_CATEGORY = Q(transaction_type__transaction_category="expense")


def get_tenant_base_currency() -> AccountingCurrency | None:
    currency = AccountingCurrency.objects.filter(is_base_currency=True, is_active=True).first()
    if currency:
        return currency
    return AccountingCurrency.objects.filter(is_active=True).order_by("-is_base_currency", "code").first()


def serialize_currency(currency: AccountingCurrency | None) -> dict[str, str]:
    if currency is None:
        return {"code": "", "symbol": "$"}
    return {
        "code": currency.code or "",
        "symbol": currency.symbol or currency.code or "$",
    }


def lookup_exchange_rate(
    from_currency: AccountingCurrency,
    to_currency: AccountingCurrency,
    *,
    as_of: date | None = None,
) -> Decimal | None:
    if from_currency.id == to_currency.id:
        return Decimal("1")

    anchor = as_of or date.today()
    rate_row = (
        AccountingExchangeRate.objects.filter(
            from_currency=from_currency,
            to_currency=to_currency,
            effective_date__lte=anchor,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=anchor))
        .order_by("-effective_date")
        .first()
    )
    if rate_row:
        return rate_row.rate

    inverse = (
        AccountingExchangeRate.objects.filter(
            from_currency=to_currency,
            to_currency=from_currency,
            effective_date__lte=anchor,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=anchor))
        .order_by("-effective_date")
        .first()
    )
    if inverse and inverse.rate:
        return Decimal("1") / inverse.rate
    return None


def convert_amount_to_base(
    amount: Decimal,
    currency: AccountingCurrency | None,
    *,
    as_of: date | None = None,
) -> Decimal:
    if amount == 0 or currency is None:
        return amount or Decimal("0")

    base = get_tenant_base_currency()
    if base is None or currency.id == base.id:
        return amount

    rate = lookup_exchange_rate(currency, base, as_of=as_of)
    if rate is None:
        return amount
    return amount * rate


def _posted_lines_queryset(ledger_account_ids: list, *, end_date: date | None = None):
    lines = AccountingJournalLine.objects.filter(
        journal_entry__status=AccountingJournalEntry.EntryStatus.POSTED,
        ledger_account_id__in=ledger_account_ids,
    )
    if end_date:
        lines = lines.filter(journal_entry__posting_date__lte=end_date)
    return lines


def compute_posted_ledger_balance_base(
    ledger_account_ids: list,
    *,
    end_date: date | None = None,
) -> Decimal:
    """Posted GL balance in tenant base currency (uses line base_amount)."""
    if not ledger_account_ids:
        return Decimal("0")

    lines = _posted_lines_queryset(ledger_account_ids, end_date=end_date)
    totals = lines.aggregate(
        total_debit=Coalesce(
            Sum("base_amount", filter=Q(debit_amount__gt=0)),
            Value(Decimal("0")),
        ),
        total_credit=Coalesce(
            Sum("base_amount", filter=Q(credit_amount__gt=0)),
            Value(Decimal("0")),
        ),
    )
    debit = totals["total_debit"] or Decimal("0")
    credit = totals["total_credit"] or Decimal("0")
    return debit - credit


def compute_posted_ledger_balance_native(
    ledger_account_ids: list,
    *,
    end_date: date | None = None,
) -> Decimal:
    """Posted GL balance in native transaction amounts on the lines."""
    if not ledger_account_ids:
        return Decimal("0")

    lines = _posted_lines_queryset(ledger_account_ids, end_date=end_date)
    totals = lines.aggregate(
        total_debit=Coalesce(Sum("debit_amount"), Value(Decimal("0"))),
        total_credit=Coalesce(Sum("credit_amount"), Value(Decimal("0"))),
    )
    debit = totals["total_debit"] or Decimal("0")
    credit = totals["total_credit"] or Decimal("0")
    return debit - credit


def approved_signed_base_amount_expression():
    return Case(
        When(_outflow_filter(), then=-Abs(F("base_amount"))),
        When(_inflow_filter(), then=Abs(F("base_amount"))),
        default=F("base_amount"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )


def approved_signed_native_amount_expression():
    return Case(
        When(_outflow_filter(), then=-Abs(F("amount"))),
        When(_inflow_filter(), then=Abs(F("amount"))),
        default=F("amount"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )


def sum_cash_metric_by_currency(
    queryset: QuerySet,
    *,
    income_filter: Q | None = None,
    expense_filter: Q | None = None,
    use_base: bool = False,
) -> list[dict]:
    """Group approved cash totals by transaction currency."""
    amount_field = "base_amount" if use_base else "amount"
    signed_expr = (
        approved_signed_base_amount_expression()
        if use_base
        else approved_signed_native_amount_expression()
    )

    rows = (
        queryset.values(
            "currency_id",
            "currency__code",
            "currency__symbol",
        )
        .annotate(
            total_revenue=Coalesce(
                Sum(Abs(F(amount_field)), filter=INCOME_CATEGORY),
                Value(Decimal("0")),
            ),
            total_expense=Coalesce(
                Sum(Abs(F(amount_field)), filter=EXPENSE_CATEGORY),
                Value(Decimal("0")),
            ),
            net_movement=Coalesce(Sum(signed_expr), Value(Decimal("0"))),
        )
        .order_by("currency__code")
    )

    results: list[dict] = []
    for row in rows:
        income = row["total_revenue"] or Decimal("0")
        expense = row["total_expense"] or Decimal("0")
        results.append(
            {
                "currency_code": row["currency__code"] or "",
                "currency_symbol": row["currency__symbol"] or row["currency__code"] or "",
                "total_revenue": float(income),
                "total_expense": float(expense),
                "net_cash_movement": float(row["net_movement"] or Decimal("0")),
                "net_all_flows": float(row["net_movement"] or Decimal("0")),
            }
        )
    return results


def _master_rate_row(
    from_currency: AccountingCurrency,
    to_currency: AccountingCurrency,
    *,
    as_of: date | None = None,
) -> AccountingExchangeRate | None:
    anchor = as_of or date.today()
    direct = (
        AccountingExchangeRate.objects.filter(
            from_currency=from_currency,
            to_currency=to_currency,
            effective_date__lte=anchor,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=anchor))
        .order_by("-effective_date")
        .first()
    )
    if direct:
        return direct
    return (
        AccountingExchangeRate.objects.filter(
            from_currency=to_currency,
            to_currency=from_currency,
            effective_date__lte=anchor,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=anchor))
        .order_by("-effective_date")
        .first()
    )


def resolve_exchange_rate_for_entry(
    *,
    from_currency: AccountingCurrency | None,
    to_currency: AccountingCurrency | None,
    as_of: date | None = None,
    bank_account_id=None,
) -> dict:
    """Resolve a suggested exchange rate for transaction entry."""
    from accounting.models import AccountingCashTransaction

    if from_currency is None or to_currency is None:
        return {"rate": None, "source": None}

    if from_currency.id == to_currency.id:
        return {"rate": float(Decimal("1")), "source": "same_currency"}

    rate = lookup_exchange_rate(from_currency, to_currency, as_of=as_of)
    if rate is not None:
        row = _master_rate_row(from_currency, to_currency, as_of=as_of)
        effective_date = row.effective_date.isoformat() if row else None
        return {
            "rate": float(rate),
            "source": "master",
            "effective_date": effective_date,
        }

    tx_qs = AccountingCashTransaction.objects.filter(
        currency=from_currency,
        status=AccountingCashTransaction.TransactionStatus.APPROVED,
    ).exclude(exchange_rate=Decimal("1"))
    if bank_account_id:
        tx_qs = tx_qs.filter(bank_account_id=bank_account_id)

    last_tx = tx_qs.order_by("-transaction_date", "-created_at").first()
    if last_tx and last_tx.exchange_rate:
        return {
            "rate": float(last_tx.exchange_rate),
            "source": "last_transaction",
            "reference_number": last_tx.reference_number,
            "transaction_date": last_tx.transaction_date.isoformat(),
        }

    return {"rate": None, "source": None}


def effective_payment_base_amount(
    amount,
    *,
    exchange_rate=None,
    base_amount=None,
) -> Decimal:
    """Payment amount normalized to tenant base/billing currency."""
    if base_amount is not None:
        return Decimal(str(base_amount))
    rate = Decimal(str(exchange_rate if exchange_rate is not None else 1))
    return Decimal(str(amount or 0)) * rate

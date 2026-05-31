"""Shared cash-transaction totals for accounting reports (aligned with bank balances)."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, F, Q, QuerySet, Sum
from django.db.models.functions import Abs, Coalesce

from accounting.models import AccountingBankAccount, AccountingCashTransaction
from accounting.services.post_all import build_student_payment_list_filter
from accounting.services.posting import (
    _inflow_filter,
    _outflow_filter,
    compute_bank_account_balance,
    compute_bank_account_native_balance,
)

INCOME_CATEGORY = Q(transaction_type__transaction_category="income")
EXPENSE_CATEGORY = Q(transaction_type__transaction_category="expense")


def filter_cash_by_period(
    queryset: QuerySet,
    period_start,
    period_end,
) -> QuerySet:
    if period_start:
        queryset = queryset.filter(transaction_date__gte=period_start)
    if period_end:
        queryset = queryset.filter(transaction_date__lte=period_end)
    return queryset


def approved_cash_queryset() -> QuerySet:
    return AccountingCashTransaction.objects.filter(
        status=AccountingCashTransaction.TransactionStatus.APPROVED,
    ).select_related("transaction_type", "student", "bank_account")


def sum_inflow_amount(queryset: QuerySet, *, use_base: bool = True) -> Decimal:
    """Income + transfer in (bank inflow totals)."""
    amount_field = "base_amount" if use_base else "amount"
    return queryset.filter(_inflow_filter()).aggregate(
        total=Coalesce(Sum(Abs(F(amount_field))), Decimal("0"))
    )["total"] or Decimal("0")


def sum_outflow_amount(queryset: QuerySet, *, use_base: bool = True) -> Decimal:
    """Expense + transfer out (bank outflow totals)."""
    amount_field = "base_amount" if use_base else "amount"
    return queryset.filter(_outflow_filter()).aggregate(
        total=Coalesce(Sum(Abs(F(amount_field))), Decimal("0"))
    )["total"] or Decimal("0")


def sum_income_revenue(queryset: QuerySet) -> Decimal:
    """Recognized revenue: approved income-category cash only (no transfers)."""
    return queryset.filter(INCOME_CATEGORY).aggregate(
        total=Coalesce(Sum(Abs(F("base_amount"))), Decimal("0"))
    )["total"] or Decimal("0")


def sum_expense_total(queryset: QuerySet) -> Decimal:
    """Operating expense: approved expense-category cash only (no transfers)."""
    return queryset.filter(EXPENSE_CATEGORY).aggregate(
        total=Coalesce(Sum(Abs(F("base_amount"))), Decimal("0"))
    )["total"] or Decimal("0")


def sum_period_income_minus_expense(queryset: QuerySet) -> Decimal:
    """Approved income-category cash minus expense-category cash in the queryset period."""
    return sum_income_revenue(queryset) - sum_expense_total(queryset)


def sum_approved_cash_net(queryset: QuerySet) -> Decimal:
    """Signed net approved cash in base currency (income − expense, incl. transfers)."""
    from accounting.services.posting import approved_signed_base_amount_expression

    signed = approved_signed_base_amount_expression()
    return queryset.aggregate(
        total=Coalesce(Sum(signed), Decimal("0")),
    )["total"] or Decimal("0")


def sum_approved_cash_net_native(queryset: QuerySet) -> Decimal:
    """Signed net approved cash in each transaction's native currency."""
    from accounting.services.currency_totals import approved_signed_native_amount_expression

    signed = approved_signed_native_amount_expression()
    return queryset.aggregate(
        total=Coalesce(Sum(signed), Decimal("0")),
    )["total"] or Decimal("0")


def approved_cash_for_bank_account(
    bank_account: AccountingBankAccount,
    *,
    end_date=None,
) -> QuerySet:
    queryset = approved_cash_queryset().filter(bank_account=bank_account)
    if bank_account.currency_id:
        queryset = queryset.filter(currency_id=bank_account.currency_id)
    return filter_cash_by_period(queryset, None, end_date)


def compute_bank_account_cash_on_hand(
    bank_account: AccountingBankAccount,
    *,
    end_date=None,
) -> Decimal:
    """Opening balance plus approved signed native cash activity."""
    opening = bank_account.opening_balance or Decimal("0")
    if opening and end_date and bank_account.opening_balance_date and bank_account.opening_balance_date > end_date:
        opening = Decimal("0")
    transaction_net = compute_bank_account_native_balance(bank_account, end_date=end_date)
    return opening + transaction_net


def compute_bank_account_cash_on_hand_base(
    bank_account: AccountingBankAccount,
    *,
    end_date=None,
) -> Decimal:
    """Opening balance (converted to base) plus approved signed base cash activity."""
    from accounting.services.currency_totals import convert_amount_to_base

    opening = bank_account.opening_balance or Decimal("0")
    if opening and end_date and bank_account.opening_balance_date and bank_account.opening_balance_date > end_date:
        opening = Decimal("0")
    opening_base = (
        convert_amount_to_base(
            opening,
            bank_account.currency,
            as_of=end_date or bank_account.opening_balance_date,
        )
        if opening
        else Decimal("0")
    )
    transaction_net = compute_bank_account_balance(bank_account, end_date=end_date)
    return opening_base + transaction_net


def split_tuition_and_other_income(
    queryset: QuerySet,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (tuition_income, other_income, total_income) from approved income cash."""
    income_qs = queryset.filter(INCOME_CATEGORY)
    tuition_qs = income_qs.filter(build_student_payment_list_filter()).distinct()
    tuition_total = tuition_qs.aggregate(
        total=Coalesce(Sum(Abs(F("base_amount"))), Decimal("0"))
    )["total"] or Decimal("0")
    all_income = income_qs.aggregate(
        total=Coalesce(Sum(Abs(F("base_amount"))), Decimal("0"))
    )["total"] or Decimal("0")
    other_total = all_income - tuition_total
    return tuition_total, other_total, all_income


def income_breakdown_by_type(queryset: QuerySet) -> list[dict]:
    rows = (
        queryset.filter(INCOME_CATEGORY)
        .values(
            "transaction_type_id",
            "transaction_type__name",
            "transaction_type__code",
        )
        .annotate(
            total=Coalesce(Sum(Abs(F("base_amount"))), Decimal("0")),
            transaction_count=Count("id"),
        )
        .order_by("-total", "transaction_type__name")
    )
    return [
        {
            "transaction_type_id": str(row["transaction_type_id"] or ""),
            "transaction_type": row["transaction_type__name"] or "Unknown",
            "transaction_type_code": row["transaction_type__code"] or "",
            "total": float(row["total"] or 0),
            "transaction_count": row["transaction_count"] or 0,
        }
        for row in rows
    ]


def expense_breakdown_by_type(queryset: QuerySet) -> list[dict]:
    rows = (
        queryset.filter(EXPENSE_CATEGORY)
        .values(
            "transaction_type_id",
            "transaction_type__name",
            "transaction_type__code",
        )
        .annotate(
            total=Coalesce(Sum(Abs(F("base_amount"))), Decimal("0")),
            transaction_count=Count("id"),
        )
        .order_by("-total", "transaction_type__name")
    )
    return [
        {
            "transaction_type_id": str(row["transaction_type_id"] or ""),
            "transaction_type": row["transaction_type__name"] or "Unknown",
            "transaction_type_code": row["transaction_type__code"] or "",
            "total": float(row["total"] or 0),
            "transaction_count": row["transaction_count"] or 0,
        }
        for row in rows
    ]

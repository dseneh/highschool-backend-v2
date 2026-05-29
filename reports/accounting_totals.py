"""Shared cash-transaction totals for accounting reports (aligned with bank balances)."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, F, Q, QuerySet, Sum
from django.db.models.functions import Abs, Coalesce

from accounting.models import AccountingCashTransaction
from accounting.services.post_all import build_student_payment_list_filter
from accounting.services.posting import _inflow_filter, _outflow_filter

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


def sum_inflow_amount(queryset: QuerySet) -> Decimal:
    """Income + transfer in (bank inflow totals)."""
    return queryset.filter(_inflow_filter()).aggregate(
        total=Coalesce(Sum(Abs(F("base_amount"))), Decimal("0"))
    )["total"] or Decimal("0")


def sum_outflow_amount(queryset: QuerySet) -> Decimal:
    """Expense + transfer out (bank outflow totals)."""
    return queryset.filter(_outflow_filter()).aggregate(
        total=Coalesce(Sum(Abs(F("base_amount"))), Decimal("0"))
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

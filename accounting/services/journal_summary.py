from __future__ import annotations

from decimal import Decimal

from django.db.models import Case, Count, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce

from accounting.models import AccountingJournalEntry, AccountingJournalLine, AccountingLedgerAccount


def build_journal_entry_list_summary(queryset) -> dict[str, object]:
    """Aggregate journal-entry list stats across the full filtered queryset."""
    posted_status = AccountingJournalEntry.EntryStatus.POSTED

    entry_counts = queryset.aggregate(
        total_count=Count("id"),
        posted_count=Count("id", filter=Q(status=posted_status)),
        draft_count=Count("id", filter=Q(status=AccountingJournalEntry.EntryStatus.DRAFT)),
        reversed_count=Count("id", filter=Q(status=AccountingJournalEntry.EntryStatus.REVERSED)),
    )

    posted_entry_ids = queryset.filter(status=posted_status).values("id")

    income_case = Case(
        When(
            ledger_account__account_type=AccountingLedgerAccount.AccountType.INCOME,
            then=F("credit_amount") - F("debit_amount"),
        ),
        default=Value(Decimal("0")),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    expense_case = Case(
        When(
            ledger_account__account_type=AccountingLedgerAccount.AccountType.EXPENSE,
            then=F("debit_amount") - F("credit_amount"),
        ),
        default=Value(Decimal("0")),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )

    line_totals = AccountingJournalLine.objects.filter(
        journal_entry_id__in=posted_entry_ids
    ).aggregate(
        posted_income_total=Coalesce(
            Sum(income_case),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        ),
        posted_expense_total=Coalesce(
            Sum(expense_case),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        ),
    )

    income_total = line_totals["posted_income_total"] or Decimal("0")
    expense_total = line_totals["posted_expense_total"] or Decimal("0")

    return {
        "total_count": entry_counts["total_count"] or 0,
        "posted_count": entry_counts["posted_count"] or 0,
        "draft_count": entry_counts["draft_count"] or 0,
        "reversed_count": entry_counts["reversed_count"] or 0,
        "posted_income_total": str(income_total),
        "posted_expense_total": str(expense_total),
        "posted_net_total": str(income_total - expense_total),
    }

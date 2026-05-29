"""Journal-entry list filtering helpers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db.models import Q

from accounting.models import AccountingBankAccount, AccountingJournalEntry


def _build_bank_account_journal_filter(bank_account: str) -> Q:
    bank_account_value = str(bank_account).strip()
    if not bank_account_value:
        return Q()

    account_filter = Q(account_number__iexact=bank_account_value)
    try:
        UUID(bank_account_value)
    except (ValueError, AttributeError, TypeError):
        return Q(lines__ledger_account_id__in=AccountingBankAccount.objects.filter(account_filter).values("ledger_account_id"))

    account_filter |= Q(id=bank_account_value)
    ledger_account_ids = AccountingBankAccount.objects.filter(account_filter).values("ledger_account_id")
    return Q(lines__ledger_account_id__in=ledger_account_ids)


def build_journal_entry_search_filter(search: str) -> Q:
    term = (search or "").strip()
    if not term:
        return Q()

    query = (
        Q(reference_number__icontains=term)
        | Q(description__icontains=term)
        | Q(source_reference__icontains=term)
        | Q(posted_by__icontains=term)
    )

    status_term = term.lower()
    if status_term in {
        AccountingJournalEntry.EntryStatus.DRAFT,
        AccountingJournalEntry.EntryStatus.POSTED,
        AccountingJournalEntry.EntryStatus.REVERSED,
    }:
        query |= Q(status=status_term)

    for source_value, source_label in AccountingJournalEntry._meta.get_field("source").choices:
        if status_term in {source_value, source_label.lower()}:
            query |= Q(source=source_value)

    normalized_digits = term.replace("-", "").replace("/", "").replace(",", "")
    if normalized_digits.replace(".", "").isdigit():
        query |= Q(posting_date__icontains=term)
        try:
            amount = Decimal(normalized_digits)
            query |= Q(total_debit_amount=amount) | Q(total_credit_amount=amount)
        except (InvalidOperation, ValueError):
            pass

    return query


def apply_journal_entry_list_filters(queryset, params) -> object:
    status_param = params.get("status")
    source = params.get("source")
    academic_year = params.get("academic_year")
    bank_account = params.get("bank_account")
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    amount = params.get("amount")
    amount_min = params.get("amount_min")
    amount_max = params.get("amount_max")
    search = params.get("search")
    ordering = params.get("ordering")

    if search:
        search_term = str(search).strip()
        if search_term:
            queryset = queryset.filter(build_journal_entry_search_filter(search_term))

    if status_param:
        queryset = queryset.filter(status=status_param)
    if source:
        queryset = queryset.filter(source=source)
    if academic_year:
        queryset = queryset.filter(academic_year_id=academic_year)
    if bank_account:
        bank_filter = _build_bank_account_journal_filter(bank_account)
        if bank_filter:
            queryset = queryset.filter(bank_filter).distinct()
    if start_date:
        queryset = queryset.filter(posting_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(posting_date__lte=end_date)
    if amount:
        try:
            amount_value = Decimal(amount)
            queryset = queryset.filter(
                Q(total_debit_amount=amount_value) | Q(total_credit_amount=amount_value)
            )
        except (InvalidOperation, TypeError):
            pass
    if amount_min not in (None, ""):
        try:
            queryset = queryset.filter(total_debit_amount__gte=Decimal(amount_min))
        except (InvalidOperation, TypeError):
            pass
    if amount_max not in (None, ""):
        try:
            queryset = queryset.filter(total_debit_amount__lte=Decimal(amount_max))
        except (InvalidOperation, TypeError):
            pass

    ordering_map = {
        "posting_date": "posting_date",
        "-posting_date": "-posting_date",
        "updated_at": "updated_at",
        "-updated_at": "-updated_at",
        "reference_number": "reference_number",
        "-reference_number": "-reference_number",
        "description": "description",
        "-description": "-description",
        "status": "status",
        "-status": "-status",
        "source": "source",
        "-source": "-source",
        "amount": "total_debit_amount",
        "-amount": "-total_debit_amount",
        "created_at": "created_at",
        "-created_at": "-created_at",
    }
    order_by = ordering_map.get(str(ordering or "").strip(), "-updated_at")
    return queryset.order_by(order_by, "-created_at")

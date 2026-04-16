from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.db.models import Q, Sum
from django.utils import timezone

from academics.models import AcademicYear
from accounting.models import (
    AccountingBankAccount,
    AccountingCashTransaction,
    AccountingJournalEntry,
    AccountingJournalLine,
)


def recalculate_bank_account_current_balance(bank_account: AccountingBankAccount) -> Decimal:
    """Recalculate and persist bank account balance from approved cash transactions."""
    approved_tx = bank_account.transactions.filter(
        status=AccountingCashTransaction.TransactionStatus.APPROVED
    )

    totals = approved_tx.aggregate(
        income=Sum(
            "base_amount",
            filter=Q(transaction_type__transaction_category="income"),
        ),
        expense=Sum(
            "base_amount",
            filter=Q(transaction_type__transaction_category="expense"),
        ),
    )

    opening_balance = bank_account.opening_balance or Decimal("0")
    income_total = totals.get("income") or Decimal("0")
    expense_total = totals.get("expense") or Decimal("0")
    new_balance = opening_balance + income_total - expense_total

    if bank_account.current_balance != new_balance:
        bank_account.current_balance = new_balance
        bank_account.save(update_fields=["current_balance", "updated_at"])

    return new_balance


def _resolve_academic_year(posting_date):
    """
    Resolve accounting posting period from the academic year that contains the date.

    This keeps posting period assignment fully backend-driven so clients only send
    posting/transaction dates.
    """
    academic_year = AcademicYear.objects.filter(
        start_date__lte=posting_date,
        end_date__gte=posting_date,
    ).order_by("-start_date").first()

    if not academic_year:
        raise ValidationError("No academic year found for posting date")

    return academic_year


def _resolve_posting_accounts(cash_transaction: AccountingCashTransaction):
    bank_ledger = cash_transaction.bank_account.ledger_account
    if bank_ledger is None:
        raise ValidationError("Bank account must have a linked ledger account")

    counter_ledger = cash_transaction.ledger_account or cash_transaction.transaction_type.default_ledger_account
    if counter_ledger is None:
        raise ValidationError("Transaction type must have a default ledger account or provide transaction ledger_account")

    return bank_ledger, counter_ledger


def _compute_base_amount(cash_transaction: AccountingCashTransaction) -> Decimal:
    if cash_transaction.base_amount:
        return cash_transaction.base_amount
    rate = cash_transaction.exchange_rate or Decimal("1")
    return cash_transaction.amount * rate


def post_cash_transaction_to_ledger(cash_transaction: AccountingCashTransaction, actor=None) -> AccountingJournalEntry:
    if cash_transaction.journal_entry_id:
        return cash_transaction.journal_entry

    if cash_transaction.status != AccountingCashTransaction.TransactionStatus.APPROVED:
        raise ValidationError("Only approved transactions can be posted")

    bank_ledger, counter_ledger = _resolve_posting_accounts(cash_transaction)
    academic_year = _resolve_academic_year(cash_transaction.transaction_date)

    posted_by = None
    if actor is not None:
        posted_by = getattr(actor, "username", None) or getattr(actor, "email", None) or str(actor)

    tx_category = cash_transaction.transaction_type.transaction_category
    if tx_category not in {"income", "expense"}:
        raise ValidationError("Only income and expense transaction categories are supported by this endpoint")

    with db_transaction.atomic():
        journal_entry = AccountingJournalEntry.objects.create(
            posting_date=cash_transaction.transaction_date,
            reference_number=f"JE-{cash_transaction.reference_number}",
            source="manual",
            description=cash_transaction.description,
            status=AccountingJournalEntry.EntryStatus.POSTED,
            academic_year=academic_year,
            posted_by=posted_by,
            posted_at=timezone.now(),
            source_reference=cash_transaction.reference_number,
        )

        base_amount = _compute_base_amount(cash_transaction)

        if tx_category == "income":
            debit_account = bank_ledger
            credit_account = counter_ledger
        else:
            debit_account = counter_ledger
            credit_account = bank_ledger

        AccountingJournalLine.objects.create(
            journal_entry=journal_entry,
            ledger_account=debit_account,
            currency=cash_transaction.currency,
            amount=cash_transaction.amount,
            debit_amount=cash_transaction.amount,
            credit_amount=Decimal("0"),
            exchange_rate=cash_transaction.exchange_rate,
            base_amount=base_amount,
            description=f"Debit for {cash_transaction.reference_number}",
            line_sequence=1,
        )

        AccountingJournalLine.objects.create(
            journal_entry=journal_entry,
            ledger_account=credit_account,
            currency=cash_transaction.currency,
            amount=cash_transaction.amount,
            debit_amount=Decimal("0"),
            credit_amount=cash_transaction.amount,
            exchange_rate=cash_transaction.exchange_rate,
            base_amount=base_amount,
            description=f"Credit for {cash_transaction.reference_number}",
            line_sequence=2,
        )

        cash_transaction.journal_entry = journal_entry
        cash_transaction.save(update_fields=["journal_entry", "updated_at"])

    return journal_entry


def reverse_cash_transaction_journal_entry(
    cash_transaction: AccountingCashTransaction,
    actor=None,
) -> AccountingJournalEntry | None:
    """Create reversing entry for a posted cash transaction and unlink it from the transaction."""
    original_entry = cash_transaction.journal_entry
    if original_entry is None:
        return None

    if original_entry.status == AccountingJournalEntry.EntryStatus.REVERSED:
        cash_transaction.journal_entry = None
        cash_transaction.save(update_fields=["journal_entry", "updated_at"])
        return None

    posted_by = None
    if actor is not None:
        posted_by = getattr(actor, "username", None) or getattr(actor, "email", None) or str(actor)

    with db_transaction.atomic():
        reversal_entry = AccountingJournalEntry.objects.create(
            posting_date=timezone.now().date(),
            reference_number=f"REV-{original_entry.reference_number}",
            source="manual",
            description=f"Reversal of {original_entry.reference_number}: {original_entry.description}",
            status=AccountingJournalEntry.EntryStatus.POSTED,
            academic_year=original_entry.academic_year,
            posted_by=posted_by,
            posted_at=timezone.now(),
            reversal_of=original_entry,
            source_reference=cash_transaction.reference_number,
        )

        for line in original_entry.lines.all().order_by("line_sequence", "created_at"):
            AccountingJournalLine.objects.create(
                journal_entry=reversal_entry,
                ledger_account=line.ledger_account,
                currency=line.currency,
                amount=line.amount,
                debit_amount=line.credit_amount,
                credit_amount=line.debit_amount,
                exchange_rate=line.exchange_rate,
                base_amount=line.base_amount,
                description=f"Reversal line for {cash_transaction.reference_number}",
                line_sequence=line.line_sequence,
            )

        original_entry.status = AccountingJournalEntry.EntryStatus.REVERSED
        original_entry.save(update_fields=["status", "updated_at"])

        cash_transaction.journal_entry = None
        cash_transaction.save(update_fields=["journal_entry", "updated_at"])

    return reversal_entry

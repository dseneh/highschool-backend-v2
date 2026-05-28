from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from accounting.models import (
    AccountingJournalEntry,
    AccountingJournalLine,
    AccountingLedgerAccount,
    AccountingPaymentMethod,
    AccountingTransactionType,
)


def _actor_label(actor) -> str | None:
    if actor is None:
        return None
    return getattr(actor, "username", None) or getattr(actor, "email", None) or str(actor)


def _ledger_by_code(code: str) -> AccountingLedgerAccount:
    account = AccountingLedgerAccount.objects.filter(code=code, is_active=True).first()
    if account is None:
        raise ValidationError(f"Ledger account {code} is not configured.")
    return account


def _resolve_payroll_transaction_type() -> AccountingTransactionType:
    from payroll_v2.models import PayrollSettings

    settings = PayrollSettings.objects.select_related("transaction_type").first()
    if settings and settings.transaction_type_id:
        tx_type = settings.transaction_type
        if tx_type.is_active:
            return tx_type
        raise ValidationError("The configured payroll transaction type is inactive.")

    tx_type = AccountingTransactionType.objects.filter(code="PAYROLL", is_active=True).first()
    if tx_type is None:
        raise ValidationError(
            "Payroll transaction type is not configured. Set it in Payroll settings."
        )
    return tx_type


def _resolve_payment_method() -> AccountingPaymentMethod:
    method = AccountingPaymentMethod.objects.filter(is_active=True).order_by("name").first()
    if method is None:
        raise ValidationError("At least one active payment method is required to post payroll.")
    return method


def _add_journal_line(
    *,
    journal_entry: AccountingJournalEntry,
    ledger_account: AccountingLedgerAccount,
    currency,
    debit: Decimal,
    credit: Decimal,
    description: str,
    line_sequence: int,
) -> None:
    amount = debit if debit > 0 else credit
    AccountingJournalLine.objects.create(
        journal_entry=journal_entry,
        ledger_account=ledger_account,
        currency=currency,
        amount=amount,
        debit_amount=debit,
        credit_amount=credit,
        exchange_rate=Decimal("1"),
        base_amount=amount,
        description=description,
        line_sequence=line_sequence,
    )


def _reverse_journal_entry(
    original_entry: AccountingJournalEntry,
    *,
    actor=None,
    description_prefix: str = "Reversal of",
) -> AccountingJournalEntry:
    posted_by = _actor_label(actor)
    reversal_entry = AccountingJournalEntry.objects.create(
        posting_date=timezone.now().date(),
        reference_number=f"REV-{original_entry.reference_number}",
        source=original_entry.source,
        description=f"{description_prefix} {original_entry.reference_number}: {original_entry.description}",
        status=AccountingJournalEntry.EntryStatus.POSTED,
        academic_year=original_entry.academic_year,
        posted_by=posted_by,
        posted_at=timezone.now(),
        reversal_of=original_entry,
        source_reference=original_entry.source_reference,
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
            description=f"Reversal line for {original_entry.reference_number}",
            line_sequence=line.line_sequence,
        )

    original_entry.status = AccountingJournalEntry.EntryStatus.REVERSED
    original_entry.save(update_fields=["status", "updated_at"])
    return reversal_entry

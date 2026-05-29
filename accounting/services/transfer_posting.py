"""Account-to-account transfer GL posting."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.utils import timezone

from accounting.models import (
    AccountingAccountTransfer,
    AccountingCashTransaction,
    AccountingJournalEntry,
    AccountingJournalLine,
)
from accounting.services.posting import _resolve_academic_year, recalculate_bank_account_current_balance
from accounting.services.settings_services import (
    bank_accounts_missing_ledger_message,
    resolve_transfer_in_account,
    resolve_transfer_out_account,
)


def _actor_label(actor) -> str | None:
    if actor is None:
        return None
    return getattr(actor, "username", None) or getattr(actor, "email", None) or str(actor)


def _add_line(
    *,
    journal_entry,
    ledger_account,
    currency,
    debit: Decimal,
    credit: Decimal,
    line_sequence: int,
    description: str,
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


@db_transaction.atomic
def post_account_transfer_to_ledger(
    transfer: AccountingAccountTransfer,
    *,
    actor=None,
) -> AccountingJournalEntry:
    """Post an account transfer using the configured transfer GL accounts."""
    from_ledger = transfer.from_account.ledger_account
    to_ledger = transfer.to_account.ledger_account
    missing_ledger_accounts = []
    if from_ledger is None:
        missing_ledger_accounts.append(transfer.from_account)
    if to_ledger is None:
        missing_ledger_accounts.append(transfer.to_account)
    if missing_ledger_accounts:
        raise ValidationError(bank_accounts_missing_ledger_message(missing_ledger_accounts))

    transfer_in_ledger = resolve_transfer_in_account()
    transfer_out_ledger = resolve_transfer_out_account()
    academic_year = _resolve_academic_year(transfer.transfer_date)
    posted_by = _actor_label(actor)

    amount = Decimal(transfer.amount or 0)
    to_amount = Decimal(transfer.to_amount or transfer.amount or 0)
    if amount <= 0 or to_amount <= 0:
        raise ValidationError("Transfer amount must be greater than zero.")

    journal_entry = AccountingJournalEntry.objects.create(
        posting_date=transfer.transfer_date,
        reference_number=transfer.reference_number,
        source="bank_transfer",
        description=transfer.description or f"Transfer to {transfer.to_account.account_name}",
        status=AccountingJournalEntry.EntryStatus.POSTED,
        academic_year=academic_year,
        posted_by=posted_by,
        posted_at=timezone.now(),
        source_reference=transfer.reference_number,
    )

    sequence = 1
    same_currency = transfer.from_currency_id == transfer.to_currency_id

    if same_currency and amount == to_amount:
        _add_line(
            journal_entry=journal_entry,
            ledger_account=to_ledger,
            currency=transfer.to_currency,
            debit=to_amount,
            credit=Decimal("0"),
            line_sequence=sequence,
            description=f"Transfer in — {transfer.to_account.account_name}",
        )
        sequence += 1
        _add_line(
            journal_entry=journal_entry,
            ledger_account=from_ledger,
            currency=transfer.from_currency,
            debit=Decimal("0"),
            credit=amount,
            line_sequence=sequence,
            description=f"Transfer out — {transfer.from_account.account_name}",
        )
    else:
        _add_line(
            journal_entry=journal_entry,
            ledger_account=to_ledger,
            currency=transfer.to_currency,
            debit=to_amount,
            credit=Decimal("0"),
            line_sequence=sequence,
            description=f"Transfer in — {transfer.to_account.account_name}",
        )
        sequence += 1
        _add_line(
            journal_entry=journal_entry,
            ledger_account=transfer_in_ledger,
            currency=transfer.to_currency,
            debit=Decimal("0"),
            credit=to_amount,
            line_sequence=sequence,
            description="Transfer in clearing",
        )
        sequence += 1
        _add_line(
            journal_entry=journal_entry,
            ledger_account=transfer_out_ledger,
            currency=transfer.from_currency,
            debit=amount,
            credit=Decimal("0"),
            line_sequence=sequence,
            description="Transfer out clearing",
        )
        sequence += 1
        _add_line(
            journal_entry=journal_entry,
            ledger_account=from_ledger,
            currency=transfer.from_currency,
            debit=Decimal("0"),
            credit=amount,
            line_sequence=sequence,
            description=f"Transfer out — {transfer.from_account.account_name}",
        )

    recalculate_bank_account_current_balance(transfer.from_account)
    recalculate_bank_account_current_balance(transfer.to_account)

    return journal_entry


def backfill_transfer_cash_transaction_journal_links() -> int:
    """Repair completed transfers whose cash txs were not linked to the GL entry."""
    updated = 0

    for transfer in AccountingAccountTransfer.objects.filter(
        status=AccountingAccountTransfer.TransferStatus.COMPLETED,
    ).only("id", "reference_number"):
        journal_entry = (
            AccountingJournalEntry.objects.filter(
                source_reference=transfer.reference_number,
                source="bank_transfer",
            )
            .order_by("-created_at")
            .first()
        )
        if journal_entry is None:
            continue

        linked = AccountingCashTransaction.objects.filter(
            source_reference=transfer.reference_number,
            journal_entry__isnull=True,
        ).update(journal_entry=journal_entry)
        updated += linked

    return updated

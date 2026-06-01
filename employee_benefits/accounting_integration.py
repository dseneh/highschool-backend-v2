from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.utils import timezone

from accounting.models import AccountingCashTransaction, AccountingJournalEntry
from accounting.services.payroll_posting import _add_journal_line, _actor_label, _resolve_payment_method, _reverse_journal_entry
from accounting.services.posting import (
    _resolve_academic_year,
    recalculate_bank_account_current_balance,
    resolve_transaction_type_counter_ledger,
)
from accounting.services.settings_services import bank_accounts_missing_ledger_message

from .models import BenefitRequest, BenefitSettings


def _benefit_reference_number(request: BenefitRequest) -> str:
    request_id = str(request.id)
    base = f"EB-{request_id[:8]}"
    prior = AccountingJournalEntry.objects.filter(
        source="employee_benefit",
        source_reference=request_id,
    ).count()
    if prior == 0:
        return base
    return f"{base}-R{prior}"


def _resolve_benefit_expense_account(settings: BenefitSettings):
    if not settings or not settings.transaction_type_id:
        raise ValidationError("Employee benefit expense transaction type is not configured.")
    return resolve_transaction_type_counter_ledger(settings.transaction_type)


@db_transaction.atomic
def post_benefit_request_to_ledger(request: BenefitRequest, *, actor=None) -> AccountingJournalEntry:
    request_id = str(request.id)

    existing = AccountingJournalEntry.objects.filter(
        source="employee_benefit",
        source_reference=request_id,
        status=AccountingJournalEntry.EntryStatus.POSTED,
    ).first()
    if existing:
        return existing

    if not request.bank_account_id:
        raise ValidationError("Benefit request must have a disbursement bank account.")

    bank_account = request.bank_account
    if bank_account.ledger_account_id is None:
        raise ValidationError(bank_accounts_missing_ledger_message([bank_account]))

    total = request.total_amount or Decimal("0.00")
    if total <= 0:
        raise ValidationError("Cannot post a benefit request with zero total.")

    currency = request.currency or bank_account.currency
    if currency is None:
        raise ValidationError("Benefit request currency is not configured.")
    if bank_account.currency_id != currency.id:
        raise ValidationError("Bank account currency must match the request currency.")

    available = recalculate_bank_account_current_balance(bank_account)
    if total > available:
        raise ValidationError(
            f"Insufficient balance in {bank_account.account_name}. "
            f"Available: {available:,.2f}, required: {total:,.2f}."
        )

    from .settings_services import get_tenant_benefit_settings

    settings = get_tenant_benefit_settings()
    expense_account = _resolve_benefit_expense_account(settings)
    payment_method = _resolve_payment_method()

    posting_date = request.payment_date
    academic_year = _resolve_academic_year(posting_date)
    posted_by = _actor_label(actor)
    reference_number = _benefit_reference_number(request)
    benefit_name = request.benefit_type.name

    journal_entry = AccountingJournalEntry.objects.create(
        posting_date=posting_date,
        reference_number=reference_number,
        source="employee_benefit",
        description=f"Employee benefit - {benefit_name} ({request.request_number})",
        status=AccountingJournalEntry.EntryStatus.POSTED,
        academic_year=academic_year,
        posted_by=posted_by,
        posted_at=timezone.now(),
        source_reference=request_id,
    )

    _add_journal_line(
        journal_entry=journal_entry,
        ledger_account=expense_account,
        currency=currency,
        debit=total,
        credit=Decimal("0"),
        description=f"{benefit_name} expense",
        line_sequence=1,
    )
    _add_journal_line(
        journal_entry=journal_entry,
        ledger_account=bank_account.ledger_account,
        currency=currency,
        debit=Decimal("0"),
        credit=total,
        description=f"{benefit_name} disbursement",
        line_sequence=2,
    )

    AccountingCashTransaction.objects.create(
        transaction_date=posting_date,
        reference_number=reference_number,
        bank_account=bank_account,
        transaction_type=settings.transaction_type,
        payment_method=payment_method,
        amount=total,
        base_amount=total,
        exchange_rate=Decimal("1.000000"),
        currency=currency,
        description=f"Employee benefit - {benefit_name} ({request.request_number})",
        status=AccountingCashTransaction.TransactionStatus.APPROVED,
        approved_by=posted_by,
        approved_at=timezone.now(),
        source_reference=request_id,
        journal_entry=journal_entry,
        created_by=actor,
        updated_by=actor,
    )

    recalculate_bank_account_current_balance(bank_account)
    return journal_entry


@db_transaction.atomic
def reverse_benefit_request_posting(request: BenefitRequest, *, actor=None):
    request_id = str(request.id)
    journal = AccountingJournalEntry.objects.filter(
        source="employee_benefit",
        source_reference=request_id,
        status=AccountingJournalEntry.EntryStatus.POSTED,
    ).first()
    if not journal:
        return

    _reverse_journal_entry(
        journal,
        actor=actor,
        description_prefix="Employee benefit reversal of",
    )

    AccountingCashTransaction.objects.filter(journal_entry=journal).update(
        status=AccountingCashTransaction.TransactionStatus.REJECTED,
        updated_by=actor,
    )

    if request.bank_account_id:
        recalculate_bank_account_current_balance(request.bank_account)

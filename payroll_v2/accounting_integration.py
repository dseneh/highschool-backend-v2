from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.utils import timezone

from accounting.models import (
    AccountingCashTransaction,
    AccountingJournalEntry,
    AccountingPayrollPostingBatch,
)
from accounting.services.payroll_posting import (
    _add_journal_line,
    _actor_label,
    _resolve_payment_method,
    _resolve_payroll_transaction_type,
)
from accounting.services.posting import _resolve_academic_year, recalculate_bank_account_current_balance
from accounting.services.settings_services import (
    bank_accounts_missing_ledger_message,
    resolve_payroll_ledger_accounts,
)

from .models import PayrollRunRecord


def aggregate_payroll_v2_run_totals(run: PayrollRunRecord) -> dict[str, Decimal]:
    combined_deductions = run.deduction_total or Decimal("0.00")
    tax = run.tax_total or Decimal("0.00")
    return {
        "gross": run.gross_pay_total or Decimal("0.00"),
        "tax": tax,
        # deduction_total includes tax; ledger 2003 is non-tax withholdings only
        "deductions": combined_deductions - tax,
        "net": run.net_pay_total or Decimal("0.00"),
    }


def _payroll_v2_reference_number(run: PayrollRunRecord) -> str:
    run_id = str(run.id)
    base = f"PR-{run_id[:8]}"
    prior_entries = AccountingJournalEntry.objects.filter(
        source="payroll",
        source_reference=run_id,
    ).count()
    if prior_entries == 0:
        return base
    return f"{base}-R{prior_entries}"


@db_transaction.atomic
def post_payroll_v2_run_to_ledger(run: PayrollRunRecord, *, actor=None) -> AccountingPayrollPostingBatch:
    run_id = str(run.id)
    idempotent_key = f"payroll-v2-run-{run_id[:8]}"

    existing_posted = (
        AccountingPayrollPostingBatch.objects.filter(
            idempotent_key=idempotent_key,
            batch_status=AccountingPayrollPostingBatch.BatchStatus.POSTED,
        )
        .select_related("journal_entry")
        .first()
    )
    if existing_posted:
        return existing_posted

    if not run.bank_account_id:
        raise ValidationError("Payroll run must have a disbursement bank account.")

    bank_account = run.bank_account
    if bank_account.ledger_account_id is None:
        raise ValidationError(bank_accounts_missing_ledger_message([bank_account]))

    if not run.employee_items.exists():
        raise ValidationError("Cannot post payroll with no employee items.")

    totals = aggregate_payroll_v2_run_totals(run)
    gross = totals["gross"]
    tax = totals["tax"]
    deductions = totals["deductions"]
    net = totals["net"]

    if gross != tax + deductions + net:
        raise ValidationError("Payroll totals do not balance for posting.")

    currency = run.currency or bank_account.currency
    if currency is None:
        raise ValidationError("Payroll run currency is not configured.")
    if bank_account.currency_id != currency.id:
        raise ValidationError("Bank account currency must match the payroll run currency.")

    available_balance = recalculate_bank_account_current_balance(bank_account)
    if net > available_balance:
        raise ValidationError(
            f"Insufficient balance in {bank_account.account_name}. "
            f"Available: {available_balance:,.2f}, payroll net pay: {net:,.2f}."
        )

    posting_date = run.payment_date
    academic_year = _resolve_academic_year(posting_date)
    posted_by = _actor_label(actor)
    reference_number = _payroll_v2_reference_number(run)
    period_label = run.payroll_period.name if run.payroll_period_id else run.payroll_number

    payroll_ledgers = resolve_payroll_ledger_accounts()
    salary_expense = payroll_ledgers["salary_expense"]
    tax_payable = payroll_ledgers["tax_payable"]
    deductions_payable = payroll_ledgers["deductions_payable"]

    batch = AccountingPayrollPostingBatch.objects.filter(idempotent_key=idempotent_key).first()
    if batch is None:
        batch = AccountingPayrollPostingBatch.objects.create(
            payroll_run_id=None,
            posting_date=posting_date,
            academic_year=academic_year,
            batch_status=AccountingPayrollPostingBatch.BatchStatus.PENDING,
            gross_amount=gross,
            tax_amount=tax,
            net_amount=net,
            currency=currency,
            idempotent_key=idempotent_key,
            notes=f"Payroll v2 run {run.payroll_number}",
        )
    else:
        batch.posting_date = posting_date
        batch.academic_year = academic_year
        batch.batch_status = AccountingPayrollPostingBatch.BatchStatus.PENDING
        batch.gross_amount = gross
        batch.tax_amount = tax
        batch.net_amount = net
        batch.currency = currency
        batch.notes = f"Payroll v2 run {run.payroll_number}"
        batch.journal_entry = None
        batch.posted_by = None
        batch.posted_at = None
        batch.save(
            update_fields=[
                "posting_date",
                "academic_year",
                "batch_status",
                "gross_amount",
                "tax_amount",
                "net_amount",
                "currency",
                "notes",
                "journal_entry",
                "posted_by",
                "posted_at",
                "updated_at",
            ]
        )

    journal_entry = AccountingJournalEntry.objects.create(
        posting_date=posting_date,
        reference_number=reference_number,
        source="payroll",
        description=f"Payroll v2 disbursement — {period_label}",
        status=AccountingJournalEntry.EntryStatus.POSTED,
        academic_year=academic_year,
        posted_by=posted_by,
        posted_at=timezone.now(),
        source_reference=run_id,
    )

    sequence = 1
    _add_journal_line(
        journal_entry=journal_entry,
        ledger_account=salary_expense,
        currency=currency,
        debit=gross,
        credit=Decimal("0"),
        description="Salaries expense",
        line_sequence=sequence,
    )
    sequence += 1

    if tax > 0:
        _add_journal_line(
            journal_entry=journal_entry,
            ledger_account=tax_payable,
            currency=currency,
            debit=Decimal("0"),
            credit=tax,
            description="Payroll tax withheld",
            line_sequence=sequence,
        )
        sequence += 1

    if deductions > 0:
        _add_journal_line(
            journal_entry=journal_entry,
            ledger_account=deductions_payable,
            currency=currency,
            debit=Decimal("0"),
            credit=deductions,
            description="Payroll deductions withheld",
            line_sequence=sequence,
        )
        sequence += 1

    _add_journal_line(
        journal_entry=journal_entry,
        ledger_account=bank_account.ledger_account,
        currency=currency,
        debit=Decimal("0"),
        credit=net,
        description="Net payroll paid",
        line_sequence=sequence,
    )

    tx_type = _resolve_payroll_transaction_type()
    payment_method = _resolve_payment_method()
    AccountingCashTransaction.objects.create(
        bank_account=bank_account,
        transaction_date=posting_date,
        reference_number=reference_number,
        transaction_type=tx_type,
        payment_method=payment_method,
        amount=net,
        currency=currency,
        exchange_rate=Decimal("1"),
        base_amount=net,
        payer_payee="Payroll",
        description=f"Payroll v2 payment — {period_label}",
        status=AccountingCashTransaction.TransactionStatus.APPROVED,
        approved_by=posted_by,
        approved_at=timezone.now(),
        source_reference=run_id,
        journal_entry=journal_entry,
    )

    batch.journal_entry = journal_entry
    batch.batch_status = AccountingPayrollPostingBatch.BatchStatus.POSTED
    batch.posted_by = posted_by
    batch.posted_at = timezone.now()
    batch.save(
        update_fields=[
            "journal_entry",
            "batch_status",
            "posted_by",
            "posted_at",
            "updated_at",
        ]
    )

    recalculate_bank_account_current_balance(bank_account)
    return batch


@db_transaction.atomic
def reverse_payroll_v2_run_posting(run: PayrollRunRecord, *, actor=None) -> AccountingPayrollPostingBatch | None:
    """Reverse GL/cash posting when a paid v2 run is reverted to draft."""
    from accounting.services.payroll_posting import _reverse_journal_entry

    run_id = str(run.id)
    idempotent_key = f"payroll-v2-run-{run_id[:8]}"
    reference = f"PR-{run_id[:8]}"
    batch = (
        AccountingPayrollPostingBatch.objects.filter(
            idempotent_key=idempotent_key,
            batch_status=AccountingPayrollPostingBatch.BatchStatus.POSTED,
        )
        .select_related("journal_entry")
        .first()
    )

    bank_account = run.bank_account

    if batch is not None:
        journal_entry = batch.journal_entry
        if journal_entry and journal_entry.status == AccountingJournalEntry.EntryStatus.POSTED:
            _reverse_journal_entry(
                journal_entry,
                actor=actor,
                description_prefix="Payroll v2 reversal of",
            )
        batch.batch_status = AccountingPayrollPostingBatch.BatchStatus.REVERSED
        batch.save(update_fields=["batch_status", "updated_at"])

    AccountingCashTransaction.objects.filter(source_reference=run_id).delete()
    AccountingCashTransaction.objects.filter(reference_number=reference).delete()

    if bank_account is not None:
        recalculate_bank_account_current_balance(bank_account)

    return batch

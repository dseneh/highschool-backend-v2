from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounting.models import (
    AccountingBankAccount,
    AccountingCashTransaction,
    AccountingJournalEntry,
    AccountingJournalLine,
    AccountingLedgerAccount,
    AccountingPaymentMethod,
    AccountingPayrollPostingBatch,
    AccountingTransactionType,
)
from accounting.services.posting import _resolve_academic_year, recalculate_bank_account_current_balance
from payroll.models import PayrollRun


def _payroll_run_id(run: PayrollRun) -> str:
    return str(run.id)


def _payroll_reference_number(run: PayrollRun) -> str:
    base = f"PAYROLL-{_payroll_run_id(run)[:8]}"
    prior_entries = AccountingJournalEntry.objects.filter(
        source="payroll",
        source_reference=_payroll_run_id(run),
    ).count()
    if prior_entries == 0:
        return base
    return f"{base}-R{prior_entries}"


def _payroll_idempotent_key(run: PayrollRun) -> str:
    return f"payroll-run-{_payroll_run_id(run)[:8]}"


def _actor_label(actor) -> str | None:
    if actor is None:
        return None
    return getattr(actor, "username", None) or getattr(actor, "email", None) or str(actor)


def _ledger_by_code(code: str) -> AccountingLedgerAccount:
    account = AccountingLedgerAccount.objects.filter(code=code, is_active=True).first()
    if account is None:
        raise ValidationError(f"Ledger account {code} is not configured.")
    return account


def aggregate_payroll_run_totals(run: PayrollRun) -> dict[str, Decimal]:
    agg = run.payslips.aggregate(
        gross=Coalesce(Sum("gross_pay"), Decimal("0")),
        tax=Coalesce(Sum("tax"), Decimal("0")),
        deductions=Coalesce(Sum("deductions"), Decimal("0")),
        net=Coalesce(Sum("net_pay"), Decimal("0")),
    )
    return {
        "gross": agg["gross"] or Decimal("0"),
        "tax": agg["tax"] or Decimal("0"),
        "deductions": agg["deductions"] or Decimal("0"),
        "net": agg["net"] or Decimal("0"),
    }


def _resolve_payroll_transaction_type() -> AccountingTransactionType:
    from payroll.models import PayrollSettings

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


@db_transaction.atomic
def post_payroll_run_to_ledger(run: PayrollRun, *, actor=None) -> AccountingPayrollPostingBatch:
    """Post an approved payroll run to GL and record the net cash disbursement."""
    idempotent_key = _payroll_idempotent_key(run)
    existing_posted = (
        AccountingPayrollPostingBatch.objects.filter(
            idempotent_key=idempotent_key,
            batch_status=AccountingPayrollPostingBatch.BatchStatus.POSTED,
        )
        .select_related("journal_entry", "payroll_run__bank_account")
        .first()
    )
    if existing_posted:
        return existing_posted

    if not run.bank_account_id:
        raise ValidationError("Assign a bank account to this payroll run before marking it paid.")

    bank_account: AccountingBankAccount = run.bank_account
    if bank_account.ledger_account_id is None:
        raise ValidationError("The selected bank account must have a linked ledger account.")

    if not run.payslips.exists():
        raise ValidationError("Cannot post payroll with no payslips.")

    totals = aggregate_payroll_run_totals(run)
    gross = totals["gross"]
    tax = totals["tax"]
    deductions = totals["deductions"]
    net = totals["net"]

    if gross != tax + deductions + net:
        raise ValidationError("Payroll totals do not balance for posting.")

    currency = run.currency
    if bank_account.currency_id != currency.id:
        raise ValidationError("Bank account currency must match the payroll schedule currency.")

    available_balance = recalculate_bank_account_current_balance(bank_account)
    if net > available_balance:
        raise ValidationError(
            f"Insufficient balance in {bank_account.account_name}. "
            f"Available: {available_balance:,.2f}, payroll net pay: {net:,.2f}."
        )

    posting_date = run.period.payment_date
    academic_year = _resolve_academic_year(posting_date)
    posted_by = _actor_label(actor)
    reference_number = _payroll_reference_number(run)

    salary_expense = _ledger_by_code("5001")
    tax_payable = _ledger_by_code("2002")
    deductions_payable = _ledger_by_code("2003")

    batch = AccountingPayrollPostingBatch.objects.filter(idempotent_key=idempotent_key).first()
    if batch is None:
        batch = AccountingPayrollPostingBatch.objects.create(
            payroll_run=run,
            posting_date=posting_date,
            academic_year=academic_year,
            batch_status=AccountingPayrollPostingBatch.BatchStatus.PENDING,
            gross_amount=gross,
            tax_amount=tax,
            net_amount=net,
            currency=currency,
            idempotent_key=idempotent_key,
            notes=f"Payroll run {run.period.name}",
        )
    else:
        batch.payroll_run = run
        batch.posting_date = posting_date
        batch.academic_year = academic_year
        batch.batch_status = AccountingPayrollPostingBatch.BatchStatus.PENDING
        batch.gross_amount = gross
        batch.tax_amount = tax
        batch.net_amount = net
        batch.currency = currency
        batch.notes = f"Payroll run {run.period.name}"
        batch.journal_entry = None
        batch.posted_by = None
        batch.posted_at = None
        batch.save(
            update_fields=[
                "payroll_run",
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
        description=f"Payroll disbursement — {run.period.name}",
        status=AccountingJournalEntry.EntryStatus.POSTED,
        academic_year=academic_year,
        posted_by=posted_by,
        posted_at=timezone.now(),
        source_reference=str(run.id),
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
        description=f"Payroll payment — {run.period.name}",
        status=AccountingCashTransaction.TransactionStatus.APPROVED,
        approved_by=posted_by,
        approved_at=timezone.now(),
        source_reference=str(run.id),
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
def reverse_payroll_run_posting(run: PayrollRun, *, actor=None) -> AccountingPayrollPostingBatch | None:
    """Reverse GL/cash posting when a paid run is reverted to draft."""
    batch = (
        AccountingPayrollPostingBatch.objects.filter(
            payroll_run=run,
            batch_status=AccountingPayrollPostingBatch.BatchStatus.POSTED,
        )
        .select_related("journal_entry", "payroll_run__bank_account")
        .first()
    )

    bank_account = run.bank_account
    run_id = _payroll_run_id(run)
    reference_number = _payroll_reference_number(run)

    if batch is not None:
        journal_entry = batch.journal_entry
        if journal_entry and journal_entry.status == AccountingJournalEntry.EntryStatus.POSTED:
            _reverse_journal_entry(
                journal_entry,
                actor=actor,
                description_prefix="Payroll reversal of",
            )

        batch.batch_status = AccountingPayrollPostingBatch.BatchStatus.REVERSED
        batch.save(update_fields=["batch_status", "updated_at"])

    AccountingCashTransaction.objects.filter(source_reference=run_id).delete()
    AccountingCashTransaction.objects.filter(reference_number=reference_number).delete()
    AccountingCashTransaction.objects.filter(reference_number=f"PAYROLL-{run_id}").delete()

    if bank_account is not None:
        recalculate_bank_account_current_balance(bank_account)

    return batch

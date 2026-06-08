"""
Payment Allocation Service - Handles dual-write logic for finance transactions to accounting.

This service bridges finance transaction creation/updates to accounting cash transactions
and payment allocations, ensuring both systems stay in sync during the transition period.

Design note (May 2026):
    ``AccountingCashTransaction`` is the single source of truth for "what the
    student paid." ``AccountingStudentBill.paid_amount`` is a denormalized
    cache derived from cash transactions, rebuilt by
    :func:`recompute_student_year_payments`. No ingestion path writes to
    ``paid_amount`` directly; the helper is invoked automatically through a
    ``post_save`` signal on ``AccountingCashTransaction``.
"""
import logging
from decimal import Decimal
from typing import Optional, Tuple

from django.db import transaction as db_transaction
from django.db.models import Q, Sum
from django.utils import timezone

from accounting.models import (
    AccountingCashTransaction,
    AccountingCurrency,
    AccountingPaymentMethod,
    AccountingStudentBill,
    AccountingTransactionType,
)


logger = logging.getLogger(__name__)


def sync_finance_transaction_to_accounting(
    finance_transaction: "Transaction",  # type: ignore
    created: bool = True,
) -> Tuple[Optional[AccountingCashTransaction], Optional[str]]:
    """
    Sync a finance.Transaction to accounting models.

    Creates/updates AccountingCashTransaction and allocates payment to student bill lines.
    This is idempotent: same finance transaction always produces same accounting records.

    Args:
        finance_transaction: finance.Transaction instance (expected to be newly created or updated)
        created: True if this is a new transaction, False if update

    Returns:
        Tuple of (AccountingCashTransaction or None, error_message or None)
    """
    error_msg = None

    try:
        # Only sync approved or income-type transactions
        if finance_transaction.status not in ["approved", "pending"]:
            return None, None

        # Only sync income (payments) and expense transactions, not transfers
        if not hasattr(finance_transaction.type, "type") or \
           finance_transaction.type.type not in ["income", "expense"]:
            return None, None

        student = finance_transaction.student
        academic_year = finance_transaction.academic_year

        if not student or not academic_year:
            return None, None

        # Find or create the mapping: finance transaction ID -> accounting cash transaction
        with db_transaction.atomic():
            accounting_tx, _ = _create_or_update_cash_transaction(finance_transaction)

            if accounting_tx:
                # If it's an income (payment), refresh the student's bill
                # paid_amount cache for this academic year. The signal on
                # AccountingCashTransaction also covers this path, but call
                # it explicitly here so callers don't depend on signals being
                # connected (and so the recompute is in the same DB
                # transaction as the cash-transaction write).
                if (
                    finance_transaction.type.type == "income"
                    and finance_transaction.status == "approved"
                ):
                    recompute_student_year_payments(student, academic_year)

        return accounting_tx, error_msg

    except Exception as e:
        error_msg = f"Failed to sync transaction to accounting: {str(e)}"
        return None, error_msg


def _create_or_update_cash_transaction(
    finance_transaction: "Transaction",  # type: ignore
) -> Tuple[Optional[AccountingCashTransaction], bool]:
    """
    Create or update AccountingCashTransaction from finance Transaction.

    Uses finance_transaction.reference as the unique key (via source_reference).
    Returns (cash_transaction, created_flag).
    """
    try:
        # Map finance transaction reference to accounting source_reference
        # This ensures idempotency: same finance TX always maps to same accounting TX
        source_reference = finance_transaction.reference or f"fin-{finance_transaction.id}"

        # Get or infer accounting entities from finance
        accounting_currency, _ = AccountingCurrency.objects.get_or_create(
            code=finance_transaction.account.currency.code if finance_transaction.account else "XOF",
            defaults={"name": finance_transaction.account.currency.name if finance_transaction.account else ""}
        )

        accounting_payment_method, _ = AccountingPaymentMethod.objects.get_or_create(
            code=finance_transaction.payment_method.code if finance_transaction.payment_method else "manual",
            defaults={"name": finance_transaction.payment_method.name if finance_transaction.payment_method else "Manual"}
        )

        accounting_bank_account = None
        if finance_transaction.account:
            accounting_bank_account = finance_transaction.account.accounting_equivalent

        accounting_tx_type = _get_or_create_transaction_type(finance_transaction.type)

        # Map finance transaction status to accounting status
        accounting_status = "approved" if finance_transaction.status == "approved" else "pending"

        cash_tx, created = AccountingCashTransaction.objects.get_or_create(
            source_reference=source_reference,
            defaults={
                "bank_account": accounting_bank_account,
                "transaction_date": finance_transaction.date,
                "transaction_type": accounting_tx_type,
                "payment_method": accounting_payment_method,
                "ledger_account": None,  # Will be assigned during posting
                "amount": abs(Decimal(str(finance_transaction.amount))),
                "currency": accounting_currency,
                "exchange_rate": Decimal("1"),
                "base_amount": abs(Decimal(str(finance_transaction.amount))),
                "payer_payee": finance_transaction.student.first_name + " " + finance_transaction.student.last_name 
                               if finance_transaction.student else "",
                "description": finance_transaction.description or "Synced from finance transaction",
                "status": accounting_status,
                "approved_by": finance_transaction.updated_by,
                "approved_at": timezone.now() if accounting_status == "approved" else None,
                "rejection_reason": None,
                "active": True,
                "student": getattr(finance_transaction, "student", None),
            }
        )

        if not created:
            update_fields = []
            # Update existing if status changed
            if cash_tx.status != accounting_status:
                cash_tx.status = accounting_status
                update_fields.append("status")
                if accounting_status == "approved":
                    cash_tx.approved_at = timezone.now()
                    cash_tx.approved_by = finance_transaction.updated_by
                    update_fields += ["approved_at", "approved_by"]
            # Backfill the student FK if a finance-side student is available
            # but the accounting row never got linked (legacy or out-of-band
            # creation paths).
            finance_student = getattr(finance_transaction, "student", None)
            if finance_student and cash_tx.student_id is None:
                cash_tx.student = finance_student
                update_fields.append("student")
            if update_fields:
                cash_tx.save(update_fields=update_fields)

        return cash_tx, created

    except Exception as e:
        return None, False


def _get_or_create_transaction_type(finance_tx_type: "TransactionType") -> AccountingTransactionType:  # type: ignore
    """Get or create matching accounting transaction type."""
    # Map finance transaction types to accounting categories
    category_map = {
        "income": "receipt",
        "expense": "payment",
        "transfer": "transfer",
    }
    category = category_map.get(getattr(finance_tx_type, "type", "income"), "receipt")

    accounting_type, _ = AccountingTransactionType.objects.get_or_create(
        code=finance_tx_type.code if hasattr(finance_tx_type, "code") else finance_tx_type.name.lower().replace(" ", "_"),
        defaults={
            "name": finance_tx_type.name,
            "transaction_category": category,
            "is_active": True,
        }
    )
    return accounting_type


def _build_student_match_q(student) -> Q:
    """OR-clause that finds cash transactions belonging to a student.

    Primary match is the direct ``student`` FK (set on every transaction
    created after the FK landed). The other clauses are backward-compat
    fallbacks for legacy rows where the student was only discoverable via
    ``source_reference`` or the ``bill_allocations`` chain.
    """
    student_refs = [str(student.id)]
    if getattr(student, "id_number", None):
        student_refs.append(student.id_number)
    if getattr(student, "prev_id_number", None):
        student_refs.append(student.prev_id_number)

    return (
        Q(student=student)
        | Q(source_reference__in=student_refs)
        | Q(bill_allocations__student_bill__student=student)
    )


def build_student_match_q_outerref() -> Q:
    """Same matching rules as ``_build_student_match_q`` for queryset annotations."""
    from django.db.models import CharField, OuterRef
    from django.db.models.functions import Cast

    return (
        Q(student=OuterRef("pk"))
        | Q(source_reference=OuterRef("id_number"))
        | Q(source_reference=OuterRef("prev_id_number"))
        | Q(source_reference=Cast(OuterRef("pk"), CharField()))
        | Q(bill_allocations__student_bill__student=OuterRef("pk"))
    )


def get_total_paid_for_student_year(student, academic_year) -> Decimal:
    """Sum of approved cash transactions a student paid in an academic year.

    Uses the direct ``student`` FK as the canonical match path with legacy
    fallbacks for rows that pre-date the FK.
    """
    if not student or not academic_year:
        return Decimal("0")

    # Two-step aggregation: find matching IDs first, then sum amounts on
    # the deduped set. Doing ``.distinct().aggregate(Sum(...))`` directly
    # is unsafe because the ``bill_allocations`` join can multiply rows.
    matched_ids = list(
        AccountingCashTransaction.objects.filter(
            _build_student_match_q(student),
            status="approved",
            transaction_date__gte=academic_year.start_date,
            transaction_date__lte=academic_year.end_date,
        )
        .values_list("id", flat=True)
        .distinct()
    )
    if not matched_ids:
        return Decimal("0")

    total = (
        AccountingCashTransaction.objects.filter(id__in=matched_ids)
        .aggregate(total=Sum("amount"))["total"]
    )
    return Decimal(str(total or 0))


def recompute_student_year_payments(student, academic_year) -> Decimal:
    """Rebuild ``AccountingStudentBill.paid_amount`` for one student/year.

    Sums approved cash transactions then distributes the total across the
    student's bills oldest-first (by ``bill_date`` then ``due_date``).
    Each bill's ``outstanding_amount`` and ``status`` are updated to stay
    consistent with ``paid_amount``.

    Idempotent: same inputs always yield the same per-bill state, so this
    is safe to call from signals, ingestion paths, or batch backfills.
    Returns the total approved amount applied across the bills.
    """
    if not student or not academic_year:
        return Decimal("0")

    try:
        with db_transaction.atomic():
            bills = list(
                AccountingStudentBill.objects.select_for_update()
                .filter(student=student, academic_year=academic_year)
                .order_by("bill_date", "due_date", "id")
            )
            if not bills:
                return Decimal("0")

            total_paid = get_total_paid_for_student_year(student, academic_year)
            remaining = total_paid
            today = timezone.now().date()

            for bill in bills:
                net = Decimal(str(bill.net_amount or 0))
                if remaining > 0 and net > 0:
                    apply = min(net, remaining)
                else:
                    apply = Decimal("0")

                new_outstanding = max(Decimal("0"), net - apply)

                # Preserve terminal states; otherwise reflect current paid
                # vs. due-date position.
                if bill.status == AccountingStudentBill.BillStatus.CANCELLED:
                    new_status = bill.status
                elif net > 0 and apply >= net:
                    new_status = AccountingStudentBill.BillStatus.PAID
                elif (
                    bill.due_date
                    and bill.due_date < today
                    and new_outstanding > 0
                ):
                    new_status = AccountingStudentBill.BillStatus.OVERDUE
                else:
                    new_status = AccountingStudentBill.BillStatus.ISSUED

                changed_fields = []
                if Decimal(str(bill.paid_amount or 0)) != apply:
                    bill.paid_amount = apply
                    changed_fields.append("paid_amount")
                if Decimal(str(bill.outstanding_amount or 0)) != new_outstanding:
                    bill.outstanding_amount = new_outstanding
                    changed_fields.append("outstanding_amount")
                if bill.status != new_status:
                    bill.status = new_status
                    changed_fields.append("status")
                if changed_fields:
                    bill.save(update_fields=changed_fields)

                remaining -= apply

            return total_paid
    except Exception as exc:
        logger.warning(
            "Failed to recompute student bill paid_amount for "
            "student=%s academic_year=%s: %s",
            getattr(student, "id", None),
            getattr(academic_year, "id", None),
            exc,
        )
        return Decimal("0")


def create_cash_transaction_from_finance_data(
    student,  # type: ignore
    academic_year,  # type: ignore
    amount: Decimal,
    payment_method_code: str = "manual",
    description: str = "",
    transaction_date = None,
) -> Tuple[Optional[AccountingCashTransaction], Optional[str]]:
    """
    Create an accounting cash transaction from scratch (for cases where finance TX may not exist yet).

    Used as an alternative entry point when creating payments directly in accounting.
    """
    try:
        if not student or not academic_year:
            return None, "Student and academic year are required"

        if amount <= 0:
            return None, "Amount must be positive"

        # Get the base currency (assuming this is inferred from context)
        # In a real setup, this would be configurable
        accounting_currency, _ = AccountingCurrency.objects.get_or_create(
            code="XOF",  # Default to school currency
            defaults={"name": "West African CFA franc"}
        )

        accounting_payment_method, _ = AccountingPaymentMethod.objects.get_or_create(
            code=payment_method_code,
            defaults={"name": payment_method_code.replace("_", " ").title()}
        )

        # Create receipt type if not exists
        receipt_type, _ = AccountingTransactionType.objects.get_or_create(
            code="receipt_payment",
            defaults={
                "name": "Payment Receipt",
                "transaction_category": "receipt",
                "is_active": True,
            }
        )

        cash_tx = AccountingCashTransaction.objects.create(
            bank_account=None,  # Can be set later via API
            transaction_date=transaction_date or timezone.now().date(),
            transaction_type=receipt_type,
            payment_method=accounting_payment_method,
            ledger_account=None,
            amount=amount,
            currency=accounting_currency,
            exchange_rate=Decimal("1"),
            base_amount=amount,
            payer_payee=f"{student.first_name} {student.last_name}",
            description=description or f"Payment from {student.first_name} {student.last_name}",
            status="pending",
            active=True,
            student=student,
        )

        # Refresh the bill paid_amount cache for this student/year so
        # downstream summaries pick up the new payment immediately. The
        # post_save signal also covers this, but call it explicitly here
        # to keep the recompute in the same DB transaction.
        recompute_student_year_payments(student, academic_year)

        return cash_tx, None

    except Exception as e:
        error_msg = f"Failed to create cash transaction: {str(e)}"
        return None, error_msg

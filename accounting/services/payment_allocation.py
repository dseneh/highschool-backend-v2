"""
Payment Allocation Service - Handles dual-write logic for finance transactions to accounting.

This service bridges finance transaction creation/updates to accounting cash transactions
and payment allocations, ensuring both systems stay in sync during the transition period.
"""
from decimal import Decimal
from typing import Optional, Tuple

from django.db import transaction as db_transaction
from django.utils import timezone

from accounting.models import (
    AccountingCashTransaction,
    AccountingCurrency,
    AccountingPaymentMethod,
    AccountingStudentBill,
    AccountingStudentBillLine,
    AccountingStudentPaymentAllocation,
    AccountingTransactionType,
)


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
                # If it's an income (payment), allocate to student bills
                if finance_transaction.type.type == "income" and finance_transaction.status == "approved":
                    _allocate_payment_to_bills(accounting_tx, student, academic_year)

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
            }
        )

        if not created:
            # Update existing if status changed
            if cash_tx.status != accounting_status:
                cash_tx.status = accounting_status
                if accounting_status == "approved":
                    cash_tx.approved_at = timezone.now()
                    cash_tx.approved_by = finance_transaction.updated_by
                cash_tx.save()

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


def _allocate_payment_to_bills(
    accounting_tx: AccountingCashTransaction,
    student,  # type: ignore
    academic_year,  # type: ignore
) -> None:
    """Allocate a payment transaction to student bill lines."""
    try:
        # Find all student bills for this enrollment in this academic year
        bills = AccountingStudentBill.objects.filter(
            enrollment__student=student,
            academic_year=academic_year,
        ).select_related("enrollment").prefetch_related("lines")

        if not bills.exists():
            return  # No bills to allocate against

        remaining_amount = accounting_tx.amount
        currency = accounting_tx.currency

        # Allocate against bill lines in order: overdue first, then upcoming
        for bill in bills:
            bill_lines = bill.lines.filter(
                outstanding_amount__gt=0
            ).order_by("-due_date", "sequence")  # Oldest/overdue first

            for line in bill_lines:
                if remaining_amount <= 0:
                    break

                allocate_amount = min(remaining_amount, line.outstanding_amount)

                # Create allocation record
                AccountingStudentPaymentAllocation.objects.get_or_create(
                    cash_transaction=accounting_tx,
                    installment_line=line,
                    defaults={
                        "student_bill": bill,
                        "allocated_amount": allocate_amount,
                        "currency": currency,
                        "allocation_date": accounting_tx.transaction_date,
                    }
                )

                # Update line outstanding amount
                line.outstanding_amount -= allocate_amount
                line.paid_amount += allocate_amount
                line.save()

                remaining_amount -= allocate_amount

            if remaining_amount <= 0:
                break

        # Update bill outstanding amounts
        for bill in bills:
            bill_lines = bill.lines.all()
            if bill_lines.exists():
                total_outstanding = sum(
                    line.outstanding_amount for line in bill_lines
                )
                bill.outstanding_amount = max(Decimal("0"), total_outstanding)
                bill.save()

    except Exception as e:
        # Log but don't fail: allocation failures shouldn't break the payment
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"Failed to allocate payment {accounting_tx.id} to student bills: {str(e)}"
        )


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
        )

        # Allocate to bills
        _allocate_payment_to_bills(cash_tx, student, academic_year)

        return cash_tx, None

    except Exception as e:
        error_msg = f"Failed to create cash transaction: {str(e)}"
        return None, error_msg

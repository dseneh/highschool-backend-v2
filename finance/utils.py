"""
Utility functions for finance calculations
"""

import logging
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


def _calculate_payment_plan_direct(enrollment, academic_year):
    """
    Direct calculation of payment plan without checking cache.
    Used when explicitly recalculating for StudentPaymentSummary.
    """
    from finance.models import PaymentInstallment

    # Get gross total bills for this enrollment
    gross_total_bills = enrollment.student_bills.aggregate(total=Sum("amount"))[
        "total"
    ] or Decimal("0")

    if gross_total_bills <= 0:
        return []

    # Calculate concessions
    total_concession = Decimal("0")
    try:
        from students.models.billing import calculate_concessions_for_enrollment
        concession_data = calculate_concessions_for_enrollment(enrollment)
        total_concession = Decimal(str(concession_data.get("total_concession", 0)))
    except Exception:
        total_concession = Decimal("0")
    
    # Payment plan percentages should be based on original total bill
    total_bills = gross_total_bills

    # Get approved payments for this academic year
    # Only count income transactions (payments received), not expenses
    approved_payments = enrollment.student.transactions.filter(
        academic_year=academic_year,
        status="approved",
        type__type="income",  # Only income transactions (payments received)
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    # Effective paid includes approved transactions + concessions
    effective_paid = approved_payments + total_concession

    # Calculate remaining balance (total bill - effective paid)
    remaining_balance = total_bills - effective_paid
    if remaining_balance <= 0:
        # Already paid in full or overpaid - no payment plan needed
        return []
    # Get active installments for this academic year, ordered by sequence
    installments = PaymentInstallment.objects.filter(
        academic_year=academic_year,
        active=True,
    ).order_by("sequence")

    if not installments.exists():
        return []

    payment_plan = []
    cumulative_percentage = Decimal("0")
    cumulative_amount = Decimal("0")
    cumulative_paid = Decimal("0")

    for installment in installments:
        # Get due date from installment
        due_date = installment.due_date

        # Value is individual percentage (e.g., 50%, 25%, 25%)
        individual_percentage = installment.value
        # Calculate installment amount based on TOTAL BILL percentages
        individual_amount = (total_bills * individual_percentage) / Decimal("100")

        # Calculate cumulative values
        cumulative_percentage += individual_percentage
        cumulative_amount += individual_amount

        # Calculate payment tracking
        previous_cumulative_amount = cumulative_amount - individual_amount

        # Calculate cumulative_paid: total paid up to this installment
        cumulative_paid = min(effective_paid, cumulative_amount)

        # Calculate amount_paid: how much of this specific installment has been paid
        if effective_paid >= cumulative_amount:
            amount_paid = individual_amount
        elif effective_paid > previous_cumulative_amount:
            amount_paid = effective_paid - previous_cumulative_amount
        else:
            amount_paid = Decimal("0")

        # Calculate balances
        balance = individual_amount - amount_paid
        cumulative_balance = cumulative_amount - cumulative_paid

        payment_plan.append(
            {
                "id": str(installment.id),
                "percentage": float(individual_percentage),
                "cumulative_percentage": float(cumulative_percentage),
                "amount": float(individual_amount),
                "cumulative_amount_due": float(cumulative_amount),
                "amount_paid": float(amount_paid),
                "cumulative_paid": float(cumulative_paid),
                "balance": float(balance),
                "cumulative_balance": float(cumulative_balance),
                "payment_date": due_date.isoformat(),
            }
        )

    return payment_plan


def _calculate_payment_status_direct(enrollment, academic_year):
    """
    Direct calculation of payment status without checking cache.
    Used when explicitly recalculating for StudentPaymentSummary.
    """
    from finance.models import PaymentInstallment
    from django.utils import timezone as tz

    today = tz.now().date()

    # Get gross total bills for this enrollment
    gross_total_bills = enrollment.student_bills.aggregate(total=Sum("amount"))[
        "total"
    ] or Decimal("0")
    
    if gross_total_bills <= 0:
        return {
            "is_on_time": True,
            "overdue_count": 0,
            "overdue_amount": 0.0,
            "overdue_percentage": 0.0,
            "expected_payment_percentage": 0.0,
            "paid_percentage": 0.0,
            "next_due_date": None,
            "total_bills": 0.0,
            "total_paid": 0.0,
            "overall_balance": 0.0,
            "is_paid_in_full": True,
        }

    # Calculate concessions
    total_concession = Decimal("0")
    try:
        from students.models.billing import calculate_concessions_for_enrollment
        concession_data = calculate_concessions_for_enrollment(enrollment)
        total_concession = Decimal(str(concession_data.get("total_concession", 0)))
    except Exception:
        total_concession = Decimal("0")
    
    # Payment status percentages should be based on original total bill
    total_bills = gross_total_bills

    # Get approved payments for this academic year
    # Only count income transactions (payments received), not expenses
    approved_payments = enrollment.student.transactions.filter(
        academic_year=academic_year,
        status="approved",
        type__type="income",  # Only income transactions (payments received)
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    # Effective paid includes approved transactions + concessions
    effective_paid = approved_payments + total_concession

    # Calculate overall balance and payment status
    total_bills_float = float(total_bills)
    effective_paid_float = float(effective_paid)
    remaining_balance = total_bills - effective_paid
    overall_balance = total_bills_float - effective_paid_float
    is_paid_in_full = total_bills > 0 and effective_paid >= total_bills

    # Calculate paid percentage
    paid_percentage = 0.0
    if total_bills > 0:
        paid_percentage = (effective_paid_float / total_bills_float) * 100.0

    if total_bills <= 0 or remaining_balance <= 0:
        return {
            "is_on_time": True,
            "overdue_count": 0,
            "overdue_amount": 0.0,
            "overdue_percentage": 0.0,
            "expected_payment_percentage": 0.0,
            "paid_percentage": 0.0,
            "next_due_date": None,
            "total_bills": 0.0,
            "total_paid": 0.0,
            "overall_balance": 0.0,
            "is_paid_in_full": True,
        }

    # Get active installments for this academic year, ordered by sequence
    installments = PaymentInstallment.objects.filter(
        academic_year=academic_year,
        active=True,
    ).order_by("sequence")

    overdue_count = 0
    overdue_amount = Decimal("0")
    next_due_date = None
    cumulative_amount_due = Decimal("0")
    expected_payment_percentage = Decimal("0")

    for installment in installments:
        due_date = installment.due_date

        # Calculate individual and cumulative amounts based on total bill percentages
        individual_percentage = installment.value
        individual_amount = (total_bills * individual_percentage) / Decimal("100")
        cumulative_amount_due += individual_amount

        # Calculate expected payment percentage
        if due_date < today:
            expected_payment_percentage += individual_percentage

            # Check if student has paid enough by this due date
            if effective_paid < cumulative_amount_due:
                overdue_for_installment = cumulative_amount_due - effective_paid
                if overdue_for_installment > 0:
                    overdue_count += 1
                    overdue_amount += min(overdue_for_installment, individual_amount)

        # Find next due date (dynamic calculation - not persisted)
        if not next_due_date and due_date >= today:
            if effective_paid >= cumulative_amount_due:
                continue
            # If due date is today, return today's date; otherwise return the due_date
            next_due_date = today if due_date == today else due_date

    is_on_time = overdue_count == 0

    # Calculate overdue percentage
    overdue_percentage = 0.0
    if total_bills > 0:
        overdue_percentage = (float(overdue_amount) / total_bills_float) * 100.0

    return {
        "is_on_time": is_on_time,
        "overdue_count": overdue_count,
        "overdue_amount": float(overdue_amount),
        "overdue_percentage": overdue_percentage,
        "expected_payment_percentage": float(expected_payment_percentage),
        "paid_percentage": paid_percentage,
        # next_due_date is calculated dynamically and not persisted
        "next_due_date": next_due_date.isoformat() if next_due_date else None,
        "total_bills": total_bills_float,
        "total_paid": effective_paid_float,
        "overall_balance": overall_balance,
        "is_paid_in_full": is_paid_in_full,
    }


def calculate_student_payment_summary(enrollment, academic_year=None):
    """
    Calculate and save student payment summary to StudentPaymentSummary table.

    This function:
    - Calculates payment_plan (expensive: iterates installments, matches payments)
    - Calculates payment_status (expensive: iterates installments, checks overdue)
    - Calculates total_paid (requires transaction join)
    - Creates or updates StudentPaymentSummary record

    Note: total_bills, total_fees, tuition, balance are NOT stored - they are
    simple SUM queries calculated on-the-fly.

    Args:
        enrollment: Enrollment instance
        academic_year: Optional academic year (defaults to enrollment's academic year)

    Returns:
        StudentPaymentSummary instance
    """
    from students.models import StudentPaymentSummary

    if not academic_year:
        academic_year = enrollment.academic_year

    # Calculate expensive operations
    # IMPORTANT: Force recalculation by bypassing cache - we're explicitly updating the summary
    # We need fresh data from installments, not cached data from the summary table
    payment_plan = _calculate_payment_plan_direct(enrollment, academic_year)
    payment_status = _calculate_payment_status_direct(enrollment, academic_year)

    # Remove next_due_date from payment_status before persisting
    # next_due_date is calculated dynamically in real-time and should not be persisted
    payment_status_for_storage = payment_status.copy()
    payment_status_for_storage.pop("next_due_date", None)

    # Calculate transactional paid (income only)
    transactional_paid = enrollment.student.transactions.filter(
        academic_year=academic_year,
        status="approved",
        type__type="income",  # Only income transactions (payments received)
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    # Calculate concessions to include in paid-equivalent value
    total_concession = Decimal("0")
    try:
        from students.models.billing import calculate_concessions_for_enrollment

        concession_data = calculate_concessions_for_enrollment(enrollment)
        total_concession = Decimal(str(concession_data.get("total_concession", 0)))
    except Exception:
        total_concession = Decimal("0")

    # Store effective paid = transaction paid + concession
    total_paid = transactional_paid + total_concession

    # Create or update summary record
    summary, created = StudentPaymentSummary.objects.update_or_create(
        enrollment=enrollment,
        academic_year=academic_year,
        defaults={
            "payment_plan": payment_plan,
            "payment_status": payment_status_for_storage,  # Store without next_due_date
            "total_paid": total_paid,
            "last_calculated_at": timezone.now(),
        },
    )

    if created:
        logger.debug(
            f"Created payment summary for enrollment {enrollment.id} "
            f"in academic year {academic_year.id}"
        )
    else:
        logger.debug(
            f"Updated payment summary for enrollment {enrollment.id} "
            f"in academic year {academic_year.id}"
        )

    return summary

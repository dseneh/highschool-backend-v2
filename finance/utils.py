"""
Utility functions for finance calculations
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

_PAYMENT_SUMMARY_REFRESH_DISABLED = ContextVar(
    "payment_summary_refresh_disabled",
    default=False,
)


def is_payment_summary_refresh_disabled() -> bool:
    return bool(_PAYMENT_SUMMARY_REFRESH_DISABLED.get())


@contextmanager
def disable_payment_summary_refresh():
    token = _PAYMENT_SUMMARY_REFRESH_DISABLED.set(True)
    try:
        yield
    finally:
        _PAYMENT_SUMMARY_REFRESH_DISABLED.reset(token)


def _calculate_payment_plan_direct(enrollment, academic_year):
    """
    Direct calculation of payment plan without checking cache.
    Used when explicitly recalculating for StudentPaymentSummary.
    """
    from finance.models import (
        _get_effective_paid_for_enrollment,
        _get_installments_for_academic_year,
        _get_net_total_bills_for_enrollment,
    )

    total_bills = _get_net_total_bills_for_enrollment(enrollment)
    if total_bills <= 0:
        return []

    effective_paid = _get_effective_paid_for_enrollment(enrollment, academic_year)

    # Calculate remaining balance (total bill - effective paid)
    remaining_balance = total_bills - effective_paid
    if remaining_balance <= 0:
        # Already paid in full or overpaid - no payment plan needed
        return []

    installments = _get_installments_for_academic_year(academic_year)
    if not installments:
        return []

    payment_plan = []
    cumulative_percentage = Decimal("0")
    cumulative_amount = Decimal("0")
    cumulative_paid = Decimal("0")

    for installment in installments:
        # Get due date from installment
        due_date = installment["due_date"]

        # Value is individual percentage (e.g., 50%, 25%, 25%)
        individual_percentage = installment["percentage"]
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
                "id": installment["id"],
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
    from finance.models import (
        _get_effective_paid_for_enrollment,
        _get_installments_for_academic_year,
        _get_net_total_bills_for_enrollment,
    )
    from django.utils import timezone as tz

    today = tz.now().date()

    total_bills = _get_net_total_bills_for_enrollment(enrollment)
    if total_bills <= 0:
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

    effective_paid = _get_effective_paid_for_enrollment(enrollment, academic_year)

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

    installments = _get_installments_for_academic_year(academic_year)

    overdue_count = 0
    overdue_amount = Decimal("0")
    next_due_date = None
    cumulative_amount_due = Decimal("0")
    expected_payment_percentage = Decimal("0")

    for installment in installments:
        due_date = installment["due_date"]

        # Calculate individual and cumulative amounts based on total bill percentages
        individual_percentage = installment["percentage"]
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
        StudentPaymentSummary instance, or None if the enrollment was already deleted.
    """
    from students.models import StudentPaymentSummary

    if is_payment_summary_refresh_disabled():
        logger.debug(
            "Payment summary refresh is temporarily disabled; skipping enrollment %s",
            getattr(enrollment, "pk", None),
        )
        return None

    if not enrollment or not getattr(enrollment, "pk", None):
        return None

    if not academic_year:
        academic_year = enrollment.academic_year

    enrollment_manager = getattr(enrollment.__class__, "_default_manager", None)
    if enrollment_manager and not enrollment_manager.filter(pk=enrollment.pk).exists():
        # Re-enrollment deletes the previous enrollment and cascades bill deletion.
        # Those delete signals can still attempt a summary refresh for the now-gone row.
        StudentPaymentSummary.objects.filter(
            enrollment_id=enrollment.pk,
            academic_year=academic_year,
        ).delete()
        logger.debug(
            "Skipping payment summary refresh for deleted enrollment %s",
            enrollment.pk,
        )
        return None

    # Calculate expensive operations
    # IMPORTANT: Force recalculation by bypassing cache - we're explicitly updating the summary
    # We need fresh data from installments, not cached data from the summary table
    payment_plan = _calculate_payment_plan_direct(enrollment, academic_year)
    payment_status = _calculate_payment_status_direct(enrollment, academic_year)

    # Remove next_due_date from payment_status before persisting
    # next_due_date is calculated dynamically in real-time and should not be persisted
    payment_status_for_storage = payment_status.copy()
    payment_status_for_storage.pop("next_due_date", None)

    from finance.models import _get_effective_paid_for_enrollment

    # Persist the same accounting-backed paid amount used by the live payment plan/status helpers.
    total_paid = _get_effective_paid_for_enrollment(enrollment, academic_year)

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

"""
Student Payment Summary model for pre-calculated payment data
"""

from django.db import models
from .base import BaseModel


class StudentPaymentSummary(BaseModel):
    """
    Denormalized table to store pre-calculated payment data for each enrollment.
    Stores expensive calculations (payment_plan, payment_status) to avoid
    recalculating on every request.

    Note: total_bills, total_fees, tuition, and balance are NOT stored because
    they are simple SUM() aggregations on indexed student_bills table (very fast).
    """

    enrollment = models.ForeignKey(
        "students.Enrollment",
        on_delete=models.CASCADE,
        related_name="payment_summary",
    )
    academic_year = models.ForeignKey(
        "academics.academicyear",
        on_delete=models.CASCADE,
        related_name="payment_summaries",
    )
    payment_plan = models.JSONField(
        default=list,
        help_text="Pre-calculated payment plan array (expensive calculation: iterates installments, matches payments)",
    )
    payment_status = models.JSONField(
        default=dict,
        help_text="Pre-calculated payment status dict (expensive calculation: iterates installments, checks overdue)",
    )
    total_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Pre-calculated total paid (requires transaction join, used in payment_plan calculations)",
    )
    last_calculated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of last calculation",
    )

    class Meta:
        db_table = 'student_payment_summary'
        verbose_name = "Student Payment Summary"
        verbose_name_plural = "Student Payment Summaries"
        unique_together = ["enrollment", "academic_year"]
        indexes = [
            models.Index(fields=["enrollment", "academic_year"]),
            models.Index(fields=["academic_year"]),
            models.Index(fields=["last_calculated_at"]),
        ]

    def __str__(self):
        return f"{self.enrollment.student.get_full_name()} - {self.academic_year.name}"

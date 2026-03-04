"""
Student model with balance calculation methods
"""
from django.core.validators import RegexValidator
from django.db import models, transaction

from academics.models import AcademicYear
from common.utils import compute_id_number, get_object_by_uuid_or_fields

from .base import BasePersonModel, Case, DecimalField, Sum, When, models

def _get_current_academic_year():
    return AcademicYear.objects.filter(current=True).first()

def get_current_academic_year(academic_year_id=None):
    academic_year = _get_current_academic_year()
    if academic_year_id:
        academic_year = AcademicYear.objects.filter(
            id=academic_year_id
        ).first()
    return academic_year

class StudentSequence(models.Model):
    """
    Per-tenant sequence counter to allocate student_seq atomically & fast.
    """

    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "student_sequence"
        verbose_name = "Student Sequence"
        verbose_name_plural = "Student Sequences"

    def __str__(self):
        return f"{self.pk} -> {self.last_seq}"


class Student(BasePersonModel):
    prev_id_number = models.CharField(
        max_length=50, blank=True, null=True, default=None
    )
    # date_of_enrollment = models.DateField(blank=True, null=True, default=None)
    date_of_graduation = models.DateField(blank=True, null=True, default=None)
    entry_date = models.DateField(blank=True, null=True, default=None)
    grade_level = models.ForeignKey(
        "academics.GradeLevel",
        on_delete=models.CASCADE,
        related_name="student_grade_level",
        blank=True,
        null=True,
        default=None,
    )
    entry_as = models.CharField(
        max_length=20,
        choices=[
            ("new", "New"),
            ("returning", "Returning"),
            ("transferred", "Transferred"),
        ],
    )
    withdrawal_date = models.DateField(blank=True, null=True, default=None)
    withdrawal_reason = models.TextField(blank=True, null=True, default=None)
    school_code = (
        models.PositiveSmallIntegerField()
    )  # 0–99 last 2 digits of school code
    student_seq = (
        models.PositiveIntegerField()
    )  # 0–9999 (or higher if you want) student sequence number

    id_number = models.CharField(
        max_length=6,
        validators=[RegexValidator(r"^\d{6}$")],
        db_index=True,
        unique=True,  # or see multi-tenant note below
        editable=False,
    )
    # Note: In a proper multi-tenant architecture, avoid cross-schema FKs
    # Consider storing user_id_number instead and looking up users via API/service layer
    user_account_id_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        help_text="Reference to User.id_number in public schema (avoid cross-schema FK)"
    )

    class Meta:
        db_table = 'student'
        constraints = [
            # Ensure uniqueness of the numeric sequence per school
            models.UniqueConstraint(
                fields=["student_seq"], name="uniq_school_student_seq"
            ),
        ]
        indexes = [
            models.Index(
                fields=["id_number"]
            ),  # fast filtering by id_number within a school
            models.Index(
                fields=["school_code", "student_seq"]
            ),  # fast ordering & “latest per school”
        ]
        # IMPORTANT: once seq goes past 9999, never order by id_number; use numeric fields:
        ordering = ["school_code", "student_seq"]

    def save(self, *args, **kwargs):
        # Ensure student_seq is allocated if not present
        if not self.student_seq:
            self.student_seq = self.allocate_next_seq()

        # Ensure school_code is set
        if not self.school_code:
            self.school_code = 1

        # keep the id_number column in sync
        if not self.id_number:
            self.id_number = compute_id_number(self.school_code, self.student_seq)

        # set default photo
        if not self.photo:
            self.photo = f"images/default_{self.gender}.jpg"

        super().save(*args, **kwargs)

    @property
    def id_number_formatted(self):
        return f"{self.school_code:02}{self.student_seq:04}"

    @classmethod
    def allocate_next_seq(cls) -> int:
        """
        O(1), race-safe allocation using a per-school counter.
        """
        with transaction.atomic():
            counter, _ = StudentSequence.objects.select_for_update().get_or_create(
                defaults={'last_seq': 0},
                id=1
            )
            counter.last_seq += 1
            counter.save(update_fields=["last_seq"])
            return counter.last_seq

    def is_enrolled(self, academic_year=None):
        """
        Check if the student is enrolled in the given academic year.
        If no academic year is provided, check for any active enrollment.
        """
        if not academic_year:
            academic_year = _get_current_academic_year()
        if not academic_year:
            return False
        return self.enrollments.filter(academic_year=academic_year).exists()

    # get balance due for the student for the current academic year
    @property
    def balance_due(self, academic_year_id=None):
        """
        Calculate the total balance due for the student in the current academic year.
        This considers only approved transactions.
        """
        return self.get_approved_balance(academic_year_id)

    def get_approved_balance(self, academic_year_id=None):
        """
        Current balance after approved payments only.
        Balance = Total Bills - approved Payments
        """
        academic_year = get_current_academic_year(academic_year_id)

        if not academic_year:
            return 0

        enrollment = self.enrollments.filter(academic_year=academic_year).first()
        if not enrollment:
            return 0

        # Get total bills
        total_bills = (
            enrollment.student_bills.aggregate(total=Sum("amount"))["total"] or 0
        )

        # Get approved payments (only income transactions that are approved)
        approved_payments = (
            self.transactions.filter(
                academic_year=academic_year,
                status="approved",
                # type__type='income'  # Only count income as payments towards balance
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        return total_bills - approved_payments

    def get_projected_balance(self, academic_year_id=None):
        """
        Projected balance if all pending payments are approved.
        Balance = Total Bills - (approved Payments + Pending Payments)
        """
        academic_year = get_current_academic_year(academic_year_id)
        if not academic_year:
            return 0

        enrollment = self.enrollments.filter(academic_year=academic_year).first()
        if not enrollment:
            return 0

        # Get total bills
        total_bills = (
            enrollment.student_bills.aggregate(total=Sum("amount"))["total"] or 0
        )

        # Get all payments (approved + pending, excluding canceled)
        all_payments = (
            self.transactions.filter(
                academic_year=academic_year,
                status__in=["approved", "pending"],
                # type__type='income'  # Only count income as payments
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        return total_bills - all_payments

    def get_balance_summary(self, academic_year_id=None):
        """
        Simple balance summary with key financial information.
        """
        academic_year = get_current_academic_year(academic_year_id)
        if not academic_year:
            return {
                "total_bills": 0,
                "approved_payments": 0,
                "pending_payments": 0,
                "canceled_payments": 0,
                "approved_balance": 0,
                "projected_balance": 0,
                "amount_pending": 0,
            }

        enrollment = self.enrollments.filter(academic_year=academic_year).first()
        if not enrollment:
            return {
                "total_bills": 0,
                "approved_payments": 0,
                "pending_payments": 0,
                "canceled_payments": 0,
                "approved_balance": 0,
                "projected_balance": 0,
                "amount_pending": 0,
            }

        # Get total bills
        total_bills = (
            enrollment.student_bills.aggregate(total=Sum("amount"))["total"] or 0
        )

        # Get payment totals by status (only income transactions)
        payment_summary = self.transactions.filter(
            academic_year=academic_year, type__type="income"
        ).aggregate(
            approved=Sum(
                Case(
                    When(status="approved", then="amount"),
                    default=0,
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            ),
            pending=Sum(
                Case(
                    When(status="pending", then="amount"),
                    default=0,
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            ),
            canceled=Sum(
                Case(
                    When(status="canceled", then="amount"),
                    default=0,
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            ),
        )

        approved_payments = payment_summary["approved"] or 0
        pending_payments = payment_summary["pending"] or 0
        canceled_payments = payment_summary["canceled"] or 0

        # Calculate balances
        approved_balance = total_bills - approved_payments
        projected_balance = total_bills - (approved_payments + pending_payments)

        return {
            "total_bills": float(total_bills),
            "approved_payments": float(approved_payments),
            "pending_payments": float(pending_payments),
            "canceled_payments": float(canceled_payments),
            "approved_balance": float(approved_balance),
            "projected_balance": float(projected_balance),
        }

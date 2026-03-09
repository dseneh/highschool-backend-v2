"""Finance models for the school management system.

All models are tenant-specific (live in tenant schemas).
"""

from django.db import models

from common.models import BaseModel


class BankAccount(BaseModel):
    """Represents a bank account for a school."""

    number = models.CharField(max_length=20, unique=True)
    bank_number = models.CharField(
        max_length=20, blank=True, null=True
    )  # Optional bank number
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} - ({self.number})"

    @property
    def balance(self):
        """Calculate the current balance of the bank account (approved transactions only)."""
        return (
            self.transactions.filter(status="approved").aggregate(models.Sum("amount"))[
                "amount__sum"
            ]
            or 0.0
        )

    def get_balance_optimized(self, approved_total=None):
        """
        Get balance with optional pre-calculated approved total to avoid duplicate queries.
        Used internally by get_analysis() to avoid redundant calculations.
        """
        if approved_total is not None:
            return float(approved_total)
        return float(self.balance)

    def get_basic_analysis(self):
        """
        Get basic analysis with just essential totals for list views.
        Much faster than full analysis - only calculates core financial metrics.
        """
        from django.db.models import Sum, Count, Q

        try:
            # Single optimized query for basic totals only
            totals = self.transactions.aggregate(
                # Transaction counts
                total_transactions=Count("id"),
                approved_count=Count("id", filter=Q(status="approved")),
                pending_count=Count("id", filter=Q(status="pending")),
                canceled_count=Count("id", filter=Q(status="canceled")),
                # Financial totals (approved only)
                total_income=Sum(
                    "amount", filter=Q(status="approved", type__type="income")
                ),
                total_expense=Sum(
                    "amount", filter=Q(status="approved", type__type="expense")
                ),
                approved_total=Sum("amount", filter=Q(status="approved")),
            )

            # Extract and clean totals
            income_total = float(totals["total_income"] or 0.0)
            expense_total = float(totals["total_expense"] or 0.0)

            return {
                "totals": {
                    "total_income": income_total,
                    "total_expense": float(
                        abs(expense_total)
                    ),  # Make positive for display
                    "net_balance": income_total + expense_total,  # expense is negative
                    "balance": self.get_balance_optimized(totals["approved_total"]),
                },
                "transaction_counts": {
                    "total_transactions": totals["total_transactions"],
                    "approved_count": totals["approved_count"],
                    "pending_count": totals["pending_count"],
                    "canceled_count": totals["canceled_count"],
                },
            }

        except Exception as e:
            # Return minimal analysis if there's an error
            try:
                balance = float(self.balance)
            except:
                balance = 0.0

            return {
                "totals": {
                    "total_income": 0.0,
                    "total_expense": 0.0,
                    "net_balance": 0.0,
                    "balance": balance,
                },
                "transaction_counts": {
                    "total_transactions": 0,
                    "approved_count": 0,
                    "pending_count": 0,
                    "canceled_count": 0,
                },
                "error": f"Basic analysis failed: {str(e)}",
            }

    def get_analysis(self):
        """
        Get comprehensive analysis of the bank account including:
        - Total income, expense, balance
        - Transaction counts by status
        - Monthly trends

        Optimized to minimize database queries using conditional aggregation.
        """
        from django.db.models import Sum, Count, Q, Case, When, DecimalField
        from django.db.models.functions import TruncMonth
        from datetime import datetime, timedelta

        try:
            # Single optimized query with conditional aggregation
            # This replaces multiple separate queries with one comprehensive query
            base_queryset = self.transactions.select_related("type", "payment_method")

            # Get all aggregated totals in a single query
            totals = base_queryset.aggregate(
                # Total counts by status
                total_transactions=Count("id"),
                approved_count=Count("id", filter=Q(status="approved")),
                pending_count=Count("id", filter=Q(status="pending")),
                canceled_count=Count("id", filter=Q(status="canceled")),
                # Financial totals (approved only)
                total_income=Sum(
                    "amount", filter=Q(status="approved", type__type="income")
                ),
                total_expense=Sum(
                    "amount", filter=Q(status="approved", type__type="expense")
                ),
                # All transactions totals by status for status breakdown
                approved_total=Sum("amount", filter=Q(status="approved")),
                pending_total=Sum("amount", filter=Q(status="pending")),
                canceled_total=Sum("amount", filter=Q(status="canceled")),
            )

            # Extract and clean totals
            income_total = float(totals["total_income"] or 0.0)
            expense_total = float(totals["total_expense"] or 0.0)

            # Build status breakdown from aggregated data
            status_breakdown = []
            for status, count_key, total_key in [
                ("approved", "approved_count", "approved_total"),
                ("pending", "pending_count", "pending_total"),
                ("canceled", "canceled_count", "canceled_total"),
            ]:
                count = totals[count_key]
                if count > 0:  # Only include statuses that have transactions
                    status_breakdown.append(
                        {
                            "status": status,
                            "count": count,
                            "total": float(totals[total_key] or 0),
                        }
                    )

            # Type breakdown for approved transactions only
            type_breakdown_query = (
                base_queryset.filter(status="approved")
                .values("type__type")
                .annotate(count=Count("id"), total=Sum("amount"))
                .order_by("type__type")
            )

            type_breakdown = [
                {
                    "type": item["type__type"],
                    "count": item["count"],
                    "total": float(
                        abs(item["total"] or 0)
                    ),  # Make positive for display
                }
                for item in type_breakdown_query
            ]

            # Monthly trends (last 12 months, approved only) - limit to recent data for performance
            twelve_months_ago = datetime.now().date() - timedelta(days=365)
            monthly_trends_query = (
                base_queryset.filter(
                    status="approved",
                    date__gte=twelve_months_ago,  # Limit to last 12 months for performance
                )
                .annotate(month=TruncMonth("date"))
                .values("month", "type__type")
                .annotate(count=Count("id"), total=Sum("amount"))
                .order_by("-month", "type__type")[:50]
            )  # Limit results for performance

            monthly_trends = [
                {
                    "month": item["month"].strftime("%Y-%m") if item["month"] else None,
                    "type": item["type__type"],
                    "count": item["count"],
                    "total": float(abs(item["total"] or 0)),
                }
                for item in monthly_trends_query
            ]

            # Payment method breakdown (approved only)
            payment_method_query = (
                base_queryset.filter(status="approved")
                .values("payment_method__name")
                .annotate(count=Count("id"), total=Sum("amount"))
                .order_by("payment_method__name")
            )

            payment_method_breakdown = [
                {
                    "payment_method": item["payment_method__name"],
                    "count": item["count"],
                    "total": float(abs(item["total"] or 0)),
                }
                for item in payment_method_query
            ]

            return {
                "totals": {
                    "total_income": income_total,
                    "total_expense": float(
                        abs(expense_total)
                    ),  # Make positive for display
                    "net_balance": income_total + expense_total,  # expense is negative
                    "balance": self.get_balance_optimized(totals["approved_total"]),
                },
                "transaction_counts": {
                    "total_transactions": totals["total_transactions"],
                    "approved_count": totals["approved_count"],
                    "pending_count": totals["pending_count"],
                    "canceled_count": totals["canceled_count"],
                },
                "status_breakdown": status_breakdown,
                "type_breakdown": type_breakdown,
                "monthly_trends": monthly_trends,
                "payment_method_breakdown": payment_method_breakdown,
            }

        except Exception as e:
            # Return empty analysis if there's an error, but still provide balance
            try:
                balance = float(self.balance)
            except:
                balance = 0.0

            return {
                "totals": {
                    "total_income": 0.0,
                    "total_expense": 0.0,
                    "net_balance": 0.0,
                    "balance": balance,
                },
                "transaction_counts": {
                    "total_transactions": 0,
                    "approved_count": 0,
                    "pending_count": 0,
                    "canceled_count": 0,
                },
                "status_breakdown": [],
                "type_breakdown": [],
                "monthly_trends": [],
                "payment_method_breakdown": [],
                "error": f"Analysis failed: {str(e)}",
            }

    class Meta:
        db_table = 'bank_account'
        ordering = ["number"]


class PaymentMethod(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True, default=None)
    is_editable = models.BooleanField(default=True)

    class Meta:
        db_table = 'payment_method'


class Currency(BaseModel):
    """A model to represent the currency used in the school."""

    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=10)
    code = models.CharField(max_length=3)  # ISO 4217 code

    def __str__(self):
        return f"{self.name} ({self.symbol})"

    class Meta:
        db_table = 'currency'


class GeneralFeeList(BaseModel):
    """Represents a single school fee type."""

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    amount = models.DecimalField(max_digits=13, decimal_places=2, default=0.0)
    student_target = models.CharField(
        max_length=100, blank=True, null=True, default=None
    )  # target student type (e.g., new, returning, transfer)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'general_fee_list'


class SectionFee(BaseModel):
    """Represents a fee associated with a specific section in a school."""

    section = models.ForeignKey(
        "academics.Section", on_delete=models.CASCADE, related_name="section_fees"
    )
    general_fee = models.ForeignKey(
        GeneralFeeList, on_delete=models.CASCADE, related_name="section_fees"
    )
    amount = models.DecimalField(max_digits=13, decimal_places=2)

    def __str__(self):
        return f"{self.general_fee.name} - {self.section.name}"

    class Meta:
        db_table = 'section_fee'


class TransactionType(BaseModel):
    """Defines the type of transaction (e.g., payment, refund)."""

    name = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    type_code = models.CharField(max_length=50)
    type = models.CharField(
        max_length=8,
        choices=[
            ("expense", "Expense"),
            ("income", "Income"),
        ],
    )
    is_hidden = models.BooleanField(default=False)
    is_editable = models.BooleanField(default=True)

    class Meta:
        db_table = 'transaction_type'
        ordering = ["name"]

    def __str__(self):
        return self.name


class Transaction(BaseModel):
    """Records a financial transaction against a student's account."""

    type = models.ForeignKey(
        TransactionType, on_delete=models.CASCADE, related_name="transactions"
    )
    account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="transactions"
    )
    transaction_id = models.CharField(max_length=100, unique=True)
    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="transactions",
    )
    academic_year = models.ForeignKey(
        "academics.academicyear", on_delete=models.CASCADE, related_name="transactions"
    )
    payment_method = models.ForeignKey(
        "finance.PaymentMethod",
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    # currency = models.ForeignKey(
    #     "finance.Currency", on_delete=models.CASCADE, related_name="transactions"
    # )
    date = models.DateField()  # Automatically set to the current date when created
    reference = models.CharField(
        max_length=100, blank=True, null=True
    )  # from receipt or other record
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=10,
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("canceled", "Canceled"),
        ],
        default="pending",
    )

    class Meta:
        db_table = 'transaction'
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.created_at} - {self.description} - {self.amount}"


class PaymentInstallment(BaseModel):
    """
    Represents a payment installment template for an academic year.
    School admins can create installments that define payment schedules.
    Student payment schedules are derived from these installments.
    Value is individual percentage (e.g., 50%, 25%, 25%). Cumulative is calculated in queries.
    """

    academic_year = models.ForeignKey(
        "academics.academicyear",
        on_delete=models.CASCADE,
        related_name="payment_installments",
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Name of the installment. Auto-generated as 'Installment {sequence}' if not provided.",
    )
    description = models.TextField(blank=True, null=True, default=None)
    value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Individual percentage (0-100) for this installment. Total of all installments should equal 100%",
    )
    due_date = models.DateField(help_text="Due date for this installment")
    sequence = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Order/sequence of this installment (1, 2, 3, ...). Auto-generated if not provided.",
    )

    class Meta:
        db_table = 'payment_installment'
        verbose_name = "Payment Installment"
        verbose_name_plural = "Payment Installments"
        ordering = ["academic_year", "sequence", "due_date"]
        indexes = [
            models.Index(fields=["academic_year", "sequence"]),
        ]
        unique_together = [["academic_year", "sequence"]]

    def save(self, *args, **kwargs):
        """Auto-generate sequence and name if not provided"""
        # Auto-generate sequence first if not provided
        if self.sequence is None:
            # Get the max sequence for this academic year and add 1
            from django.db.models import Max

            queryset = PaymentInstallment.objects.filter(
                academic_year=self.academic_year
            )
            # Exclude current instance if updating
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            max_sequence = queryset.aggregate(max_seq=Max("sequence"))["max_seq"]
            self.sequence = (max_sequence or 0) + 1

        # Auto-generate name if not provided (after sequence is set)
        if not self.name or self.name.strip() == "":
            self.name = f"Installment {self.sequence}"

        super().save(*args, **kwargs)

    def clean(self):
        """Validate that value is between 0 and 100, due_date is within academic year, and name is unique"""
        from django.core.exceptions import ValidationError

        if self.value < 0 or self.value > 100:
            raise ValidationError("Percentage value must be between 0 and 100")

        # Validate due_date is within academic year dates
        if self.academic_year and self.due_date:
            if self.due_date < self.academic_year.start_date:
                raise ValidationError(
                    f"Due date ({self.due_date}) cannot be before academic year start date ({self.academic_year.start_date})"
                )
            if self.due_date > self.academic_year.end_date:
                raise ValidationError(
                    f"Due date ({self.due_date}) cannot be after academic year end date ({self.academic_year.end_date})"
                )

            # Validate due_date uniqueness within academic year (each date must be unique)
            queryset = PaymentInstallment.objects.filter(
                academic_year=self.academic_year, due_date=self.due_date
            )
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            if queryset.exists():
                raise ValidationError(
                    f"An installment with due date '{self.due_date}' already exists for this academic year. Each installment must have a unique due date (at least one day apart)."
                )

        # Validate name uniqueness within academic year (if name is provided)
        # Note: Auto-generated names are validated after save() when sequence is set
        if self.name and self.name.strip() and self.academic_year:
            queryset = PaymentInstallment.objects.filter(
                academic_year=self.academic_year, name=self.name
            )
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            if queryset.exists():
                raise ValidationError(
                    f"An installment with the name '{self.name}' already exists for this academic year"
                )

    def calculate_amount(self, base_amount):
        """
        Calculate the amount for this installment based on its percentage.

        Args:
            base_amount: The base amount (e.g., total tuition) to calculate from

        Returns:
            Decimal: The amount for this installment
        """
        from decimal import Decimal

        return (base_amount * self.value) / Decimal("100")

    def __str__(self):
        return f"{self.name} - {self.academic_year}"


def get_student_payment_plan(enrollment, academic_year=None):
    """
    Generate a payment plan for a student enrollment based on active installments.
    Returns a list of payment schedule items with cumulative percentages and amounts,
    including payment tracking information.

    First checks StudentPaymentSummary table (persistent cache), then falls back
    to calculation if missing. Results are also cached in Redis for faster access.

    Results are automatically invalidated when:
    - A payment (Transaction) is created/updated/deleted
    - A PaymentInstallment is created/updated/deleted

    Args:
        enrollment: Student enrollment object
        academic_year: Optional academic year (defaults to enrollment's academic year)

    Returns:
        list: List of payment plan items with structure:
        [
            {
                "percentage": 50,
                "cumulative_percentage": 50,
                "amount": 500,
                "cumulative_amount_due": 500,
                "amount_paid": 300,
                "cumulative_paid": 300,
                "balance": 200,
                "cumulative_balance": 200,
                "payment_date": "2025-10-01"
            },
            ...
        ]
    """
    from decimal import Decimal
    from django.core.cache import cache
    from students.models import StudentPaymentSummary

    if not academic_year:
        academic_year = enrollment.academic_year

    # NOTE: Recalculate with live net-bill logic to avoid stale cached plans
    # generated with old gross-based concession behavior.
    cache_key = f"payment_plan:{enrollment.id}:{academic_year.id}"

    # Get total bills for this enrollment
    from django.db.models import Sum

    gross_total_bills = enrollment.student_bills.aggregate(total=Sum("amount"))[
        "total"
    ] or Decimal("0")

    if gross_total_bills <= 0:
        # Cache empty result too
        empty_plan = []
        cache.set(cache_key, empty_plan, 3600)  # 1 hour
        return empty_plan

    # Calculate concessions
    total_concession = Decimal("0")
    try:
        from students.models.billing import calculate_concessions_for_enrollment
        concession_data = calculate_concessions_for_enrollment(enrollment)
        total_concession = Decimal(str(concession_data.get("total_concession", 0)))
    except Exception:
        total_concession = Decimal("0")

    # Payment plan percentages should be based on net total bill.
    total_bills = gross_total_bills - total_concession
    if total_bills < 0:
        total_bills = Decimal("0")

    # Get approved payments for this academic year (single query for optimization)
    # Only count income transactions (payments received), not expenses
    approved_payments = enrollment.student.transactions.filter(
        academic_year=academic_year,
        status="approved",
        type__type="income",  # Only income transactions (payments received)
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    # Paid amount should only be real transactions.
    effective_paid = approved_payments

    # Calculate remaining balance (total bill - effective paid)
    remaining_balance = total_bills - effective_paid
    if remaining_balance <= 0:
        # Already paid in full or overpaid - no payment plan needed
        empty_plan = []
        cache.set(cache_key, empty_plan, 3600)  # 1 hour
        return empty_plan

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
        # previous_cumulative_amount: total amount due before this installment
        previous_cumulative_amount = cumulative_amount - individual_amount

        # Calculate cumulative_paid: total paid up to this installment
        cumulative_paid = min(effective_paid, cumulative_amount)

        # Calculate amount_paid: how much of this specific installment has been paid
        # This is the portion of effective_paid that applies to this installment
        if effective_paid >= cumulative_amount:
            # Fully paid up to this installment
            amount_paid = individual_amount
        elif effective_paid > previous_cumulative_amount:
            # Partially paid - some payment for this installment
            amount_paid = effective_paid - previous_cumulative_amount
        else:
            # Not paid yet for this installment
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

    # Cache the result in Redis for 1 hour
    cache.set(cache_key, payment_plan, 3600)  # 1 hour

    return payment_plan


def _calculate_next_due_date_dynamic(enrollment, academic_year=None):
    """
    Calculate next_due_date dynamically in real-time.
    This is not persisted and is always recalculated, even when using cached payment_status.

    Returns:
        str or None: ISO format date string, or None if all dates are in the past
    """
    from decimal import Decimal
    from django.utils import timezone
    from django.db.models import Sum

    if not academic_year:
        academic_year = enrollment.academic_year

    today = timezone.now().date()

    # Get total bills for this enrollment
    gross_total_bills = enrollment.student_bills.aggregate(total=Sum("amount"))[
        "total"
    ] or Decimal("0")

    if gross_total_bills <= 0:
        return None

    # Calculate concessions
    total_concession = Decimal("0")
    try:
        from students.models.billing import calculate_concessions_for_enrollment
        concession_data = calculate_concessions_for_enrollment(enrollment)
        total_concession = Decimal(str(concession_data.get("total_concession", 0)))
    except Exception:
        total_concession = Decimal("0")

    # Payment schedule is based on net total bill.
    total_bills = gross_total_bills - total_concession
    if total_bills < 0:
        total_bills = Decimal("0")

    # Get approved payments for this academic year
    # Only count income transactions (payments received), not expenses
    approved_payments = enrollment.student.transactions.filter(
        academic_year=academic_year,
        status="approved",
        type__type="income",  # Only income transactions (payments received)
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    # Paid amount should only be real transactions.
    effective_paid = approved_payments

    # Calculate remaining balance
    remaining_balance = total_bills - effective_paid
    if remaining_balance <= 0:
        # Already paid in full - no next due date
        return None

    installments = PaymentInstallment.objects.filter(
        academic_year=academic_year,
        active=True,
    ).order_by("sequence")

    # If no installments exist, return None
    if not installments.exists():
        return None

    next_due_date = None
    cumulative_amount_due = Decimal("0")

    for installment in installments:
        due_date = installment.due_date

        # Calculate individual and cumulative amounts based on total bill percentages
        individual_percentage = installment.value
        individual_amount = (total_bills * individual_percentage) / Decimal("100")
        cumulative_amount_due += individual_amount

        # Find next due date (dynamic calculation - not persisted)
        # Look for the first installment that is today or in the future and not yet fully paid
        if due_date >= today:
            # Check if this installment is already fully paid
            if effective_paid >= cumulative_amount_due:
                # This installment is paid, continue to next one
                continue
            # Found the next unpaid installment
            # If due date is today, return today's date; otherwise return the due_date
            next_due_date = today if due_date == today else due_date
            break  # Found the next due date, no need to continue

    # If all installments are in the past or already paid, return None
    return next_due_date.isoformat() if next_due_date else None


def get_student_payment_status(enrollment, academic_year=None):
    """
    Check if student is on time for payments or overdue.
    Calculates based on installments and student's payment transactions.

    First checks StudentPaymentSummary table (persistent cache), then falls back
    to calculation if missing. Results are also cached in Redis for faster access.

    Results are automatically invalidated when:
    - A payment (Transaction) is created/updated/deleted
    - A PaymentInstallment is created/updated/deleted

    Args:
        enrollment: Student enrollment object
        academic_year: Optional academic year (defaults to enrollment's academic year)

    Returns:
        dict: {
            "is_on_time": bool,
            "overdue_count": int,
            "overdue_amount": float,
            "overdue_percentage": float,
            "expected_payment_percentage": float,
            "paid_percentage": float,
            "next_due_date": str or None,
            "total_bills": float,
            "total_paid": float,
            "overall_balance": float,
            "is_paid_in_full": bool
        }
    """
    from decimal import Decimal
    from django.utils import timezone
    from django.db.models import Sum
    from django.core.cache import cache
    from students.models import StudentPaymentSummary

    if not academic_year:
        academic_year = enrollment.academic_year

    # NOTE: Recalculate with live net-bill logic to avoid stale cached status
    # generated with old gross-based concession behavior.
    cache_key = f"payment_status:{enrollment.id}:{academic_year.id}"

    today = timezone.now().date()

    # Get total bills for this enrollment
    gross_total_bills = enrollment.student_bills.aggregate(total=Sum("amount"))[
        "total"
    ] or Decimal("0")

    # Calculate concessions
    total_concession = Decimal("0")
    try:
        from students.models.billing import calculate_concessions_for_enrollment
        concession_data = calculate_concessions_for_enrollment(enrollment)
        total_concession = Decimal(str(concession_data.get("total_concession", 0)))
    except Exception:
        total_concession = Decimal("0")

    # Payment status percentages should be based on net total bill.
    total_bills = gross_total_bills - total_concession
    if total_bills < 0:
        total_bills = Decimal("0")

    # Get approved payments for this academic year
    # Only count income transactions (payments received), not expenses
    approved_payments = enrollment.student.transactions.filter(
        academic_year=academic_year,
        status="approved",
        type__type="income",  # Only income transactions (payments received)
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    # Paid amount should only be real transactions.
    effective_paid = approved_payments

    # Calculate overall balance and payment status
    total_bills_float = float(total_bills)
    effective_paid_float = float(effective_paid)
    remaining_balance = total_bills - effective_paid
    overall_balance = total_bills_float - effective_paid_float
    is_paid_in_full = total_bills > 0 and effective_paid >= total_bills

    # Calculate paid percentage (percentage of total bills that has been paid)
    paid_percentage = 0.0
    if total_bills > 0:
        paid_percentage = (effective_paid_float / total_bills_float) * 100.0

    if total_bills <= 0:
        # Return early status for students with no bills
        early_status = {
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
        # Cache the result
        cache.set(cache_key, early_status, 3600)  # 1 hour
        return early_status

    # Get active installments for this academic year, ordered by sequence
    installments = PaymentInstallment.objects.filter(
        academic_year=academic_year,
        active=True,
    ).order_by("sequence")

    overdue_count = 0
    overdue_amount = Decimal("0")
    next_due_date = None
    cumulative_amount_due = Decimal("0")
    expected_payment_percentage = Decimal(
        "0"
    )  # Cumulative percentage of installments past due date

    for installment in installments:
        due_date = installment.due_date

        # Calculate individual and cumulative amounts based on total bill percentages
        individual_percentage = installment.value
        individual_amount = (total_bills * individual_percentage) / Decimal("100")
        cumulative_amount_due += individual_amount

        # Calculate expected payment percentage (cumulative percentage of installments past due date)
        if due_date < today:
            # This installment's due date has passed, so it should be included in expected payment
            expected_payment_percentage += individual_percentage

            # Check if student has paid enough by this due date
            if effective_paid < cumulative_amount_due:
                # Calculate overdue amount for this installment
                overdue_for_installment = cumulative_amount_due - effective_paid
                if overdue_for_installment > 0:
                    overdue_count += 1
                    # Only count the individual amount that's overdue
                    overdue_amount += min(overdue_for_installment, individual_amount)

        # Find next due date (dynamic calculation - not persisted)
        if not next_due_date and due_date >= today:
            # Check if this installment is already paid
            if effective_paid >= cumulative_amount_due:
                continue
            # If due date is today, return today's date; otherwise return the due_date
            next_due_date = today if due_date == today else due_date

    is_on_time = overdue_count == 0

    # Calculate overdue percentage (percentage of total bills that is overdue)
    overdue_percentage = 0.0
    if total_bills > 0:
        overdue_percentage = (float(overdue_amount) / total_bills_float) * 100.0

    payment_status = {
        "is_on_time": is_on_time,
        "overdue_count": overdue_count,
        "overdue_amount": float(overdue_amount),
        "overdue_percentage": round(overdue_percentage, 2),
        "expected_payment_percentage": round(float(expected_payment_percentage), 2),
        "paid_percentage": round(paid_percentage, 2),
        # next_due_date is calculated dynamically and not persisted
        "next_due_date": next_due_date.isoformat() if next_due_date else None,
        "total_bills": total_bills_float,
        "total_paid": effective_paid_float,
        "overall_balance": overall_balance,
        "is_paid_in_full": is_paid_in_full,
    }

    # Remove next_due_date from payment_status before caching
    # next_due_date is calculated dynamically in real-time and should not be cached
    payment_status_for_cache = payment_status.copy()
    payment_status_for_cache.pop("next_due_date", None)

    # Cache the result in Redis for 1 hour (without next_due_date)
    cache.set(cache_key, payment_status_for_cache, 3600)  # 1 hour

    # Return payment_status with dynamically calculated next_due_date
    return payment_status

"""
Student accounts receivable models.
"""

from django.db import models
from decimal import Decimal

from common.models import BaseModel


class AccountingFeeItem(BaseModel):
    """Fee item catalog (tuition, general fees, activity fees, etc.)."""

    class FeeCategory(models.TextChoices):
        TUITION = "tuition", "Tuition"
        GENERAL = "general", "General Fee"
        ACTIVITY = "activity", "Activity Fee"
        OTHER = "other", "Other"

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    category = models.CharField(max_length=20, choices=FeeCategory.choices)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "accounting_fee_item"
        verbose_name = "Fee Item"
        verbose_name_plural = "Fee Items"
        ordering = ["code"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class AccountingFeeRate(BaseModel):
    """Fee rate by academic year, grade level, and student category."""

    fee_item = models.ForeignKey(
        AccountingFeeItem,
        on_delete=models.CASCADE,
        related_name="rates",
    )
    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.CASCADE,
        related_name="accounting_fee_rates",
    )
    grade_level = models.ForeignKey(
        "academics.GradeLevel",
        on_delete=models.CASCADE,
        related_name="accounting_fee_rates",
        null=True,
        blank=True,
        help_text="Leave blank to apply to all grades",
    )
    student_category = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g., new, returning, transfer",
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )

    class Meta:
        db_table = "accounting_fee_rate"
        verbose_name = "Fee Rate"
        verbose_name_plural = "Fee Rates"
        ordering = ["academic_year", "fee_item"]

    def __str__(self):
        return f"{self.fee_item.name} - {self.academic_year} - {self.amount}"


class AccountingStudentBill(BaseModel):
    """Student billing record: master bill for an enrollment."""

    class BillStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

    enrollment = models.ForeignKey(
        "students.Enrollment",
        on_delete=models.CASCADE,
        related_name="accounting_bills",
    )
    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.PROTECT,
    )
    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="accounting_bills",
    )
    grade_level = models.ForeignKey(
        "academics.GradeLevel",
        on_delete=models.PROTECT,
    )
    bill_date = models.DateField()
    due_date = models.DateField()
    gross_amount = models.DecimalField(max_digits=18, decimal_places=2)
    concession_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=18, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    outstanding_amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    status = models.CharField(max_length=20, choices=BillStatus.choices, default=BillStatus.ISSUED)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "accounting_student_bill"
        verbose_name = "Student Bill"
        verbose_name_plural = "Student Bills"
        ordering = ["-bill_date"]
        indexes = [
            models.Index(fields=["student", "academic_year"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.academic_year} - {self.net_amount}"


class AccountingStudentBillLine(BaseModel):
    """Itemized fee lines that compose a student's gross bill."""

    student_bill = models.ForeignKey(
        AccountingStudentBill,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    fee_item = models.ForeignKey(
        AccountingFeeItem,
        on_delete=models.PROTECT,
        related_name="bill_lines",
    )
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_amount = models.DecimalField(max_digits=18, decimal_places=2)
    line_amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    line_sequence = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "accounting_student_bill_line"
        verbose_name = "Student Bill Line"
        verbose_name_plural = "Student Bill Lines"
        ordering = ["student_bill", "line_sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["student_bill", "line_sequence"],
                name="unique_student_bill_line_sequence",
            ),
        ]

    def __str__(self):
        return f"{self.student_bill_id} - {self.fee_item.name} - {self.line_amount}"


class AccountingConcession(BaseModel):
    """Concession (discount/waiver) applied to a student."""

    class ConcessionType(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage"
        FLAT = "flat", "Flat Amount"

    class ConcessionTarget(models.TextChoices):
        ENTIRE_BILL = "entire_bill", "Entire Bill"
        TUITION = "tuition", "Tuition Only"
        OTHER_FEES = "other_fees", "Other Fees Only"

    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="accounting_concessions",
    )
    student_bill = models.ForeignKey(
        AccountingStudentBill,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="concessions",
        help_text="Optional explicit bill this concession was applied to",
    )
    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.CASCADE,
    )
    concession_type = models.CharField(max_length=20, choices=ConcessionType.choices)
    target = models.CharField(max_length=20, choices=ConcessionTarget.choices, default=ConcessionTarget.ENTIRE_BILL)
    value = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        help_text="Percentage (0-100) or flat amount",
    )
    computed_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Computed concession amount",
    )
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "accounting_concession"
        verbose_name = "Concession"
        verbose_name_plural = "Concessions"
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.concession_type} - {self.value}"


class AccountingInstallmentPlan(BaseModel):
    """Payment installment plan template for an academic year."""

    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.CASCADE,
        related_name="accounting_installment_plans",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "accounting_installment_plan"
        verbose_name = "Installment Plan"
        verbose_name_plural = "Installment Plans"
        ordering = ["academic_year", "name"]

    def __str__(self):
        return f"{self.name} - {self.academic_year}"


class AccountingInstallmentLine(BaseModel):
    """Individual installment within a plan."""

    installment_plan = models.ForeignKey(
        AccountingInstallmentPlan,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    sequence = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    due_date = models.DateField()
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Percentage of total bill (0-100)",
    )
    grace_days = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "accounting_installment_line"
        verbose_name = "Installment Line"
        verbose_name_plural = "Installment Lines"
        ordering = ["installment_plan", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["installment_plan", "sequence"],
                name="unique_installment_sequence",
            ),
        ]

    def __str__(self):
        return f"{self.installment_plan.name} - {self.sequence} ({self.name})"


class AccountingStudentPaymentAllocation(BaseModel):
    """Allocation of a payment against bill and installment lines."""

    student_bill = models.ForeignKey(
        AccountingStudentBill,
        on_delete=models.CASCADE,
        related_name="payment_allocations",
    )
    cash_transaction = models.ForeignKey(
        "AccountingCashTransaction",
        on_delete=models.PROTECT,
        related_name="bill_allocations",
        null=True,
        blank=True,
    )
    installment_line = models.ForeignKey(
        AccountingInstallmentLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    allocated_amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    allocation_date = models.DateField()

    class Meta:
        db_table = "accounting_student_payment_allocation"
        verbose_name = "Student Payment Allocation"
        verbose_name_plural = "Student Payment Allocations"
        ordering = ["-allocation_date"]

    def __str__(self):
        return f"{self.student_bill} - {self.allocated_amount}"


class AccountingARSnapshot(BaseModel):
    """Denormalized snapshot of student AR summary for fast reporting."""

    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="accounting_ar_snapshots",
    )
    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.CASCADE,
    )
    total_billed = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_concessions = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_net = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_paid = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    outstanding_balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ("paid_in_full", "Paid in Full"),
            ("on_time", "On Time"),
            ("overdue", "Overdue"),
            ("not_billed", "Not Billed"),
        ],
        default="not_billed",
    )
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounting_ar_snapshot"
        verbose_name = "AR Snapshot"
        verbose_name_plural = "AR Snapshots"
        ordering = ["-last_updated"]
        unique_together = [["student", "academic_year"]]

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.academic_year}"

from decimal import Decimal

from django.db import models

from common.models import BaseModel
from payroll_v2.enums import CalculationType, TargetAmountSource

from .enums import BenefitRequestStatus


class BenefitType(BaseModel):
    """Named employee benefit/allocation (e.g. Food Allotment)."""

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=50, blank=True, default="")
    description = models.TextField(blank=True)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "employee_benefit_type"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=~models.Q(code=""),
                name="employee_benefit_uniq_type_code",
            ),
        ]

    def __str__(self):
        return self.name


class BenefitTypeRule(BaseModel):
    """Calculation rule for a benefit type (brackets, flat, percentage, formula)."""

    benefit_type = models.ForeignKey(BenefitType, on_delete=models.CASCADE, related_name="rules")
    name = models.CharField(max_length=120)
    calculation_type = models.CharField(
        max_length=30,
        choices=CalculationType.choices,
        default=CalculationType.FLAT,
    )
    value = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    formula = models.TextField(blank=True)
    target_amount_source = models.CharField(
        max_length=50,
        choices=TargetAmountSource.choices,
        default=TargetAmountSource.BASIC_SALARY,
    )
    target_min_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    target_max_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    calculation_limit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    effective_start_date = models.DateField(null=True, blank=True)
    effective_end_date = models.DateField(null=True, blank=True)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "employee_benefit_type_rule"
        ordering = ["benefit_type__priority", "priority", "target_min_amount", "name"]
        indexes = [
            models.Index(fields=["benefit_type", "is_active"]),
        ]

    def __str__(self):
        return f"{self.benefit_type.name} - {self.name}"

    def is_effective_for(self, start_date, end_date):
        if not self.is_active or not self.benefit_type.is_active:
            return False
        if self.effective_start_date and self.effective_start_date > end_date:
            return False
        if self.effective_end_date and self.effective_end_date < start_date:
            return False
        return True


class EmployeeBenefit(BaseModel):
    """Per-employee assignment to a benefit type with optional calculation override."""

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.CASCADE,
        related_name="employee_benefits",
    )
    benefit_type = models.ForeignKey(
        BenefitType,
        on_delete=models.PROTECT,
        related_name="employee_assignments",
    )
    name_override = models.CharField(max_length=120, blank=True)
    calculation_type = models.CharField(
        max_length=30,
        choices=CalculationType.choices,
        default=CalculationType.FLAT,
    )
    value = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    formula = models.TextField(blank=True)
    target_amount_source = models.CharField(
        max_length=50,
        choices=TargetAmountSource.choices,
        default=TargetAmountSource.BASIC_SALARY,
    )
    calculation_limit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=100)
    calculation_overridden = models.BooleanField(
        default=False,
        help_text="When true, employee-specific calculation replaces catalog rules.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "employee_benefit_assignment"
        ordering = ["priority", "benefit_type__priority", "benefit_type__name"]
        indexes = [
            models.Index(fields=["employee", "is_active"]),
            models.Index(fields=["start_date", "end_date"]),
        ]

    def get_name(self):
        return self.name_override or self.benefit_type.name

    def is_effective_for(self, start_date, end_date):
        if not self.is_active or not self.benefit_type.is_active:
            return False
        if self.start_date and self.start_date > end_date:
            return False
        if self.end_date and self.end_date < start_date:
            return False
        return True


class BenefitRequest(BaseModel):
    """Periodic benefit disbursement request (max 30-day period, one active per type)."""

    request_number = models.CharField(max_length=50)
    benefit_type = models.ForeignKey(
        BenefitType,
        on_delete=models.PROTECT,
        related_name="requests",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    payment_date = models.DateField()
    status = models.CharField(
        max_length=30,
        choices=BenefitRequestStatus.choices,
        default=BenefitRequestStatus.DRAFT,
    )
    currency = models.ForeignKey(
        "accounting.AccountingCurrency",
        on_delete=models.PROTECT,
        related_name="benefit_requests",
        null=True,
        blank=True,
    )
    bank_account = models.ForeignKey(
        "accounting.AccountingBankAccount",
        on_delete=models.PROTECT,
        related_name="benefit_requests",
        null=True,
        blank=True,
    )
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    approved_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="benefit_requests_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    paid_table_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "employee_benefit_request"
        ordering = ["-period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["request_number"], name="employee_benefit_uniq_request_number"),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["benefit_type", "period_start", "period_end"]),
        ]

    def __str__(self):
        return self.request_number

    def recalculate_totals(self):
        self.total_amount = sum(
            (line.final_amount for line in self.lines.all()),
            Decimal("0.00"),
        )
        self.save(update_fields=["total_amount", "updated_at"])


class BenefitRequestLine(BaseModel):
    """One employee line in a benefit request."""

    request = models.ForeignKey(
        BenefitRequest,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="benefit_request_lines",
    )
    employee_benefit = models.ForeignKey(
        EmployeeBenefit,
        on_delete=models.SET_NULL,
        related_name="request_lines",
        null=True,
        blank=True,
    )
    computed_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    final_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    amount_overridden = models.BooleanField(
        default=False,
        help_text="When true, final_amount was manually set by finance.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "employee_benefit_request_line"
        ordering = ["employee__last_name", "employee__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "employee"],
                name="employee_benefit_uniq_request_employee",
            ),
        ]
        indexes = [
            models.Index(fields=["request", "employee"]),
        ]

    def __str__(self):
        return f"{self.request.request_number} - {self.employee_id}"


class BenefitSettings(BaseModel):
    """Tenant-level employee benefit accounting and cycle configuration."""

    transaction_type = models.ForeignKey(
        "accounting.AccountingTransactionType",
        on_delete=models.PROTECT,
        related_name="benefit_settings",
        null=True,
        blank=True,
        help_text="Expense transaction type used when posting benefit disbursements.",
    )
    max_period_days = models.PositiveSmallIntegerField(
        default=30,
        help_text="Maximum inclusive length of a benefit request period (in days).",
    )
    default_period_days = models.PositiveSmallIntegerField(
        default=30,
        help_text="Default period length suggested when finance creates a new request.",
    )
    min_days_between_requests = models.PositiveSmallIntegerField(
        default=1,
        help_text="Minimum days after a paid request ends before the next request may start.",
    )

    class Meta:
        db_table = "employee_benefit_settings"
        verbose_name = "Employee Benefit Settings"
        verbose_name_plural = "Employee Benefit Settings"

    def __str__(self):
        return "Employee Benefit Settings"

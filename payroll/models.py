"""Payroll models — schedules, periods, runs, payslips, recurring items, tax rules."""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone

from common.models import BaseModel


class PaySchedule(BaseModel):
    """A recurring payroll cadence for a group of employees.

    Drives auto-derivation of payroll periods, sets the currency for any
    runs/payslips created against it, and acts as the assignable schedule
    for individual employees.
    """

    class Frequency(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        BIWEEKLY = "biweekly", "Bi-Weekly"
        WEEKLY = "weekly", "Weekly"

    name = models.CharField(max_length=150)
    frequency = models.CharField(
        max_length=20,
        choices=Frequency.choices,
        default=Frequency.MONTHLY,
    )
    anchor_date = models.DateField(
        help_text="Reference date — the first period starts here; subsequent periods step from it.",
    )
    currency = models.ForeignKey(
        "accounting.AccountingCurrency",
        on_delete=models.PROTECT,
        related_name="pay_schedules",
    )
    payment_day_offset = models.PositiveSmallIntegerField(
        default=0,
        help_text="Days after period_end when payment is made.",
    )
    overtime_multiplier = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.50"),
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "pay_schedule"
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                name="payroll_uniq_pay_schedule_name_per_tenant",
            ),
            models.UniqueConstraint(
                fields=["is_default"],
                name="payroll_uniq_default_pay_schedule_per_tenant",
                condition=models.Q(is_default=True),
            ),
        ]

    def __str__(self):
        return self.name


class PayrollPeriod(BaseModel):
    """A concrete time window derived from a PaySchedule."""

    schedule = models.ForeignKey(
        PaySchedule,
        on_delete=models.PROTECT,
        related_name="periods",
    )
    name = models.CharField(max_length=150)
    start_date = models.DateField()
    end_date = models.DateField()
    payment_date = models.DateField()
    is_closed = models.BooleanField(default=False)

    class Meta:
        db_table = "payroll_period"
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "start_date", "end_date"],
                name="payroll_uniq_period_per_schedule",
            ),
        ]

    def __str__(self):
        return self.name


class PayrollRun(BaseModel):
    """A single execution of payroll against a period."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending Approval"
        APPROVED = "approved", "Approved"
        PAID = "paid", "Paid"

    period = models.ForeignKey(
        PayrollPeriod,
        on_delete=models.PROTECT,
        related_name="runs",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    notes = models.TextField(blank=True, null=True, default=None)
    approved_at = models.DateTimeField(blank=True, null=True, default=None)
    paid_at = models.DateTimeField(blank=True, null=True, default=None)

    class Meta:
        db_table = "payroll_run"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Run for {self.period.name} ({self.get_status_display()})"

    @property
    def currency(self):
        return self.period.schedule.currency


class Payslip(BaseModel):
    """Snapshot of an employee's pay for a single payroll run."""

    payroll_run = models.ForeignKey(
        PayrollRun,
        on_delete=models.CASCADE,
        related_name="payslips",
    )
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="payslips",
    )
    currency = models.ForeignKey(
        "accounting.AccountingCurrency",
        on_delete=models.PROTECT,
        related_name="payslips",
    )

    basic_salary = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    overtime_hours = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    overtime_pay = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    unpaid_leave_days = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    allowances = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    deductions = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    gross_pay = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    net_pay = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    breakdown = models.JSONField(
        default=dict,
        blank=True,
        help_text="Frozen detail: per-item allowance/deduction lines and per-rule tax breakdown.",
    )
    generated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payslip"
        ordering = ["employee__first_name", "employee__last_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["payroll_run", "employee"],
                name="payroll_uniq_payslip_per_run_employee",
            ),
        ]

    def __str__(self):
        return f"Payslip {self.employee_id} / {self.payroll_run_id}"


class PayrollItemType(BaseModel):
    """Catalog of reusable allowance/deduction types defined per tenant.

    Administrators manage the master list once (e.g. "Transport Allowance",
    "Loan Repayment", "SSF Contribution"). Each PayrollItem assigned to an
    employee references one of these catalog entries instead of free-form text.
    """

    class ItemType(models.TextChoices):
        ALLOWANCE = "allowance", "Allowance"
        DEDUCTION = "deduction", "Deduction"

    class CalculationType(models.TextChoices):
        FLAT = "flat", "Flat Amount"
        PERCENTAGE = "percentage", "Percentage"
        FORMULA = "formula", "Formula"

    class AppliesTo(models.TextChoices):
        GROSS = "gross", "Gross Pay"
        BASIC = "basic", "Basic Salary"

    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Optional short code, e.g. SSF, LOAN, TRANSPORT.",
    )
    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.ALLOWANCE,
    )
    calculation_type = models.CharField(
        max_length=20,
        choices=CalculationType.choices,
        default=CalculationType.FLAT,
        help_text="How the amount is computed when assigned to an employee.",
    )
    default_value = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text="Suggested value: amount for FLAT, percent for PERCENTAGE, ignored for FORMULA.",
    )
    default_formula = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Default Python expression for FORMULA. "
            "Available names: gross, basic, allowances, deductions, taxable_gross, min, max."
        ),
    )
    applies_to = models.CharField(
        max_length=20,
        choices=AppliesTo.choices,
        default=AppliesTo.BASIC,
        help_text="Base used for PERCENTAGE/FORMULA calculations.",
    )
    default_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Suggested fallback amount when assigning. Can be overridden per employee.",
    )
    description = models.TextField(blank=True, null=True, default=None)
    is_active = models.BooleanField(default=True)
    is_system_managed = models.BooleanField(
        default=False,
        help_text="System-managed types cannot be deleted; protected fields cannot be edited.",
    )

    class Meta:
        db_table = "payroll_item_type"
        ordering = ["item_type", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "item_type"],
                name="payroll_uniq_item_type_name_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.get_item_type_display()}: {self.name}"


class PayrollItem(BaseModel):
    """Recurring per-employee allowance or deduction."""

    class ItemType(models.TextChoices):
        ALLOWANCE = "allowance", "Allowance"
        DEDUCTION = "deduction", "Deduction"

    class CalculationType(models.TextChoices):
        FLAT = "flat", "Flat Amount"
        PERCENTAGE = "percentage", "Percentage"
        FORMULA = "formula", "Formula"

    class AppliesTo(models.TextChoices):
        GROSS = "gross", "Gross Pay"
        BASIC = "basic", "Basic Salary"

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.CASCADE,
        related_name="payroll_items",
    )
    item_type_ref = models.ForeignKey(
        "payroll.PayrollItemType",
        on_delete=models.PROTECT,
        related_name="employee_items",
        null=True,
        blank=True,
        help_text="Catalog entry. Required for new items; nullable for legacy rows only.",
    )
    name = models.CharField(max_length=150)
    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.ALLOWANCE,
    )
    calculation_type = models.CharField(
        max_length=20,
        choices=CalculationType.choices,
        default=CalculationType.FLAT,
    )
    value = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text="Amount for FLAT, percent for PERCENTAGE, ignored for FORMULA.",
    )
    formula = models.TextField(blank=True, default="")
    applies_to = models.CharField(
        max_length=20,
        choices=AppliesTo.choices,
        default=AppliesTo.BASIC,
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Cached/legacy resolved amount. Computed from value/formula at payslip time.",
    )
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField(blank=True, null=True, default=None)
    effective_to = models.DateField(blank=True, null=True, default=None)
    notes = models.TextField(blank=True, null=True, default=None)

    class Meta:
        db_table = "payroll_item"
        ordering = ["item_type", "name"]

    def __str__(self):
        return f"{self.get_item_type_display()}: {self.name}"

    def applies_on(self, on_date):
        if not self.is_active:
            return False
        if self.effective_from and on_date < self.effective_from:
            return False
        if self.effective_to and on_date > self.effective_to:
            return False
        return True


class TaxRule(BaseModel):
    """Tenant-scoped tax configuration applied during payslip generation."""

    class CalculationType(models.TextChoices):
        FLAT = "flat", "Flat Amount"
        PERCENTAGE = "percentage", "Percentage"
        FORMULA = "formula", "Formula"

    class AppliesTo(models.TextChoices):
        GROSS = "gross", "Gross Pay"
        TAXABLE_GROSS = "taxable_gross", "Taxable Gross"
        BASIC = "basic", "Basic Salary"

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30, blank=True, default="")
    description = models.TextField(blank=True, null=True, default=None)
    calculation_type = models.CharField(
        max_length=20,
        choices=CalculationType.choices,
        default=CalculationType.PERCENTAGE,
    )
    value = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text="Fixed amount for FLAT, percent (e.g. 10.5) for PERCENTAGE, ignored for FORMULA.",
    )
    formula = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Python expression evaluated when calculation_type=FORMULA. "
            "Available names: gross, basic, allowances, deductions, taxable_gross, min, max."
        ),
    )
    applies_to = models.CharField(
        max_length=20,
        choices=AppliesTo.choices,
        default=AppliesTo.GROSS,
    )
    priority = models.PositiveSmallIntegerField(
        default=100,
        help_text="Lower runs first.",
    )
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField(blank=True, null=True, default=None)
    effective_to = models.DateField(blank=True, null=True, default=None)

    class Meta:
        db_table = "tax_rule"
        ordering = ["priority", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                name="payroll_uniq_tax_rule_name_per_tenant",
            ),
            models.UniqueConstraint(
                fields=["code"],
                name="payroll_uniq_tax_rule_code_per_tenant",
                condition=~models.Q(code=""),
            ),
        ]

    def __str__(self):
        return self.name

    def applies_on(self, on_date):
        if not self.is_active:
            return False
        if self.effective_from and on_date < self.effective_from:
            return False
        if self.effective_to and on_date > self.effective_to:
            return False
        return True


class EmployeeTaxRuleOverride(BaseModel):
    """Per-employee override of a TaxRule's calculation for payroll computation.

    When present (and ``is_active=True``), the values here replace the corresponding
    fields on the rule when computing tax for this specific employee. Fields left as
    null fall through to the rule's defaults.
    """

    class CalculationType(models.TextChoices):
        FLAT = "flat", "Flat Amount"
        PERCENTAGE = "percentage", "Percentage"
        FORMULA = "formula", "Formula"

    class AppliesTo(models.TextChoices):
        GROSS = "gross", "Gross Pay"
        TAXABLE_GROSS = "taxable_gross", "Taxable Gross"
        BASIC = "basic", "Basic Salary"

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.CASCADE,
        related_name="tax_rule_overrides",
    )
    rule = models.ForeignKey(
        "payroll.TaxRule",
        on_delete=models.CASCADE,
        related_name="employee_overrides",
    )
    calculation_type = models.CharField(
        max_length=20,
        choices=CalculationType.choices,
        blank=True,
        null=True,
        default=None,
    )
    value = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
        default=None,
    )
    formula = models.TextField(blank=True, default="")
    applies_to = models.CharField(
        max_length=20,
        choices=AppliesTo.choices,
        blank=True,
        null=True,
        default=None,
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "employee_tax_rule_override"
        ordering = ["rule__priority", "rule__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "rule"],
                name="payroll_uniq_employee_tax_override",
            ),
        ]

    def __str__(self):
        return f"{self.employee_id} -> {self.rule_id} override"

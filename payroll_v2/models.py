from decimal import Decimal

from django.db import models
from django.utils import timezone

from common.models import BaseModel

from .enums import (
    CalculationType,
    Frequency,
    LineType,
    PayScheduleFrequency,
    PaymentMethod,
    PaymentStatus,
    PayrollStatus,
    PayrollType,
    PayType,
    TargetAmountSource,
)


class PaySchedule(BaseModel):
    """Recurring payroll cadence for employees and payroll runs."""

    name = models.CharField(max_length=150)
    frequency = models.CharField(
        max_length=20,
        choices=PayScheduleFrequency.choices,
        default=PayScheduleFrequency.MONTHLY,
    )
    anchor_date = models.DateField(
        help_text="Reference date — the first period starts here; subsequent periods step from it.",
    )
    currency = models.ForeignKey(
        "accounting.AccountingCurrency",
        on_delete=models.PROTECT,
        related_name="payroll_v2_pay_schedules",
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
        db_table = "payroll_v2_pay_schedule"
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(fields=["name"], name="payroll_v2_uniq_pay_schedule_name"),
            models.UniqueConstraint(
                fields=["is_default"],
                name="payroll_v2_uniq_default_pay_schedule",
                condition=models.Q(is_default=True),
            ),
        ]

    def __str__(self):
        return self.name


class PayrollPeriod(BaseModel):
    """Concrete pay period derived from a pay schedule."""

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
        db_table = "payroll_v2_payroll_period"
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "start_date", "end_date"],
                name="payroll_v2_uniq_period_per_schedule",
            ),
        ]

    def __str__(self):
        return self.name


class EmployeeCompensation(BaseModel):
    """Historical compensation record; falls back to hr.Employee fields when absent."""

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.CASCADE,
        related_name="payroll_v2_compensations",
    )
    pay_type = models.CharField(max_length=20, choices=PayType.choices, default=PayType.SALARY)
    base_amount = models.DecimalField(max_digits=14, decimal_places=2)
    hourly_rate = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    daily_rate = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    annual_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Annualized pay from base amount and the employee pay schedule frequency.",
    )
    currency = models.ForeignKey(
        "accounting.AccountingCurrency",
        on_delete=models.PROTECT,
        related_name="payroll_v2_compensations",
        null=True,
        blank=True,
    )
    effective_start_date = models.DateField()
    effective_end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_v2_compensation"
        ordering = ["-effective_start_date", "-created_at"]
        indexes = [
            models.Index(fields=["employee", "is_active"]),
            models.Index(fields=["effective_start_date", "effective_end_date"]),
        ]

    def __str__(self):
        return f"{self.employee_id} - {self.pay_type} - {self.base_amount}"


class PayrollCatalogItem(BaseModel):
    """Catalog definition for earnings, deductions, taxes, benefits, reimbursements."""

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=50, blank=True, default="")
    line_type = models.CharField(max_length=30, choices=LineType.choices)
    is_taxable = models.BooleanField(default=False)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_v2_item"
        ordering = ["priority", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=~models.Q(code=""),
                name="payroll_v2_uniq_item_code_when_set",
            ),
        ]

    def __str__(self):
        return self.name


class PayrollCatalogItemRule(BaseModel):
    payroll_item = models.ForeignKey(PayrollCatalogItem, on_delete=models.CASCADE, related_name="rules")
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
        default=TargetAmountSource.GROSS_PAY,
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
        db_table = "payroll_v2_item_rule"
        ordering = ["payroll_item__priority", "priority", "target_min_amount", "name"]
        indexes = [
            models.Index(fields=["payroll_item", "is_active"]),
            models.Index(fields=["target_amount_source", "target_min_amount", "target_max_amount"]),
        ]

    def __str__(self):
        return f"{self.payroll_item.name} - {self.name}"

    def is_effective_for(self, start_date, end_date):
        if not self.is_active or not self.payroll_item.is_active:
            return False
        if self.effective_start_date and self.effective_start_date > end_date:
            return False
        if self.effective_end_date and self.effective_end_date < start_date:
            return False
        return True


class EmployeePayrollItem(BaseModel):
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.CASCADE,
        related_name="payroll_v2_items",
    )
    payroll_item = models.ForeignKey(PayrollCatalogItem, on_delete=models.PROTECT, related_name="employee_assignments")
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
        default=TargetAmountSource.GROSS_PAY,
    )
    calculation_limit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    is_taxable = models.BooleanField(null=True, blank=True)
    is_recurring = models.BooleanField(default=False)
    frequency = models.CharField(max_length=30, choices=Frequency.choices, default=Frequency.ONE_TIME)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=100)
    calculation_overridden = models.BooleanField(
        default=False,
        help_text="When true, employee-specific calculation replaces catalog rules for this item.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_v2_employee_item"
        ordering = ["priority", "payroll_item__priority", "payroll_item__name"]
        indexes = [
            models.Index(fields=["employee", "is_active"]),
            models.Index(fields=["start_date", "end_date"]),
        ]

    def get_name(self):
        return self.name_override or self.payroll_item.name

    def get_is_taxable(self):
        return self.is_taxable if self.is_taxable is not None else self.payroll_item.is_taxable

    def is_effective_for(self, start_date, end_date):
        if not self.is_active or not self.payroll_item.is_active:
            return False
        if self.start_date and self.start_date > end_date:
            return False
        if self.end_date and self.end_date < start_date:
            return False
        return True


class PayrollTableView(BaseModel):
    """Saved payroll run table layout."""

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    is_system = models.BooleanField(default=False)
    applies_to = models.CharField(max_length=50, blank=True, default="payroll_run")
    columns = models.JSONField(default=list, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    sorting = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "payroll_v2_table_view"
        ordering = ["-is_default", "name"]
        indexes = [models.Index(fields=["is_default", "applies_to"])]

    def __str__(self):
        return self.name


class PayrollPayslipTemplate(BaseModel):
    """Saved payslip layout for preview/export."""

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    is_system = models.BooleanField(default=False)
    layout = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "payroll_v2_payslip_template"
        ordering = ["-is_default", "name"]
        indexes = [models.Index(fields=["is_default"])]

    def __str__(self):
        return self.name


class PayrollRunRecord(BaseModel):
    payroll_number = models.CharField(max_length=50)
    payroll_type = models.CharField(max_length=30, choices=PayrollType.choices, default=PayrollType.REGULAR)
    pay_period_start = models.DateField()
    pay_period_end = models.DateField()
    payment_date = models.DateField()
    pay_schedule = models.ForeignKey(
        PaySchedule,
        on_delete=models.PROTECT,
        related_name="payroll_runs",
        null=True,
        blank=True,
    )
    payroll_period = models.ForeignKey(
        PayrollPeriod,
        on_delete=models.PROTECT,
        related_name="payroll_runs",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=30, choices=PayrollStatus.choices, default=PayrollStatus.DRAFT)
    currency = models.ForeignKey(
        "accounting.AccountingCurrency",
        on_delete=models.PROTECT,
        related_name="payroll_v2_runs",
        null=True,
        blank=True,
    )
    bank_account = models.ForeignKey(
        "accounting.AccountingBankAccount",
        on_delete=models.PROTECT,
        related_name="payroll_v2_runs",
        null=True,
        blank=True,
    )
    table_view = models.ForeignKey(
        PayrollTableView,
        on_delete=models.SET_NULL,
        related_name="payroll_runs",
        null=True,
        blank=True,
    )
    table_view_snapshot = models.JSONField(default=dict, blank=True)
    payslip_template = models.ForeignKey(
        PayrollPayslipTemplate,
        on_delete=models.SET_NULL,
        related_name="payroll_runs",
        null=True,
        blank=True,
    )
    payslip_template_snapshot = models.JSONField(default=dict, blank=True)
    gross_pay_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    deduction_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    benefit_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    reimbursement_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    net_pay_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    approved_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_v2_runs_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    paid_table_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "payroll_v2_run"
        ordering = ["-pay_period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["payroll_number"], name="payroll_v2_uniq_run_number"),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["pay_period_start", "pay_period_end"]),
            models.Index(fields=["pay_schedule"]),
        ]

    def __str__(self):
        return self.payroll_number

    @property
    def can_generate(self):
        return self.status in [PayrollStatus.DRAFT, PayrollStatus.PROCESSING]

    def recalculate_totals(self):
        items = self.employee_items.all()
        self.gross_pay_total = sum((i.gross_pay for i in items), Decimal("0.00"))
        self.deduction_total = sum((i.total_deductions for i in items), Decimal("0.00"))
        self.tax_total = sum((i.total_tax for i in items), Decimal("0.00"))
        self.benefit_total = sum((i.total_benefits for i in items), Decimal("0.00"))
        self.reimbursement_total = sum((i.total_reimbursements for i in items), Decimal("0.00"))
        self.net_pay_total = sum((i.net_pay for i in items), Decimal("0.00"))
        self.save(
            update_fields=[
                "gross_pay_total",
                "deduction_total",
                "tax_total",
                "benefit_total",
                "reimbursement_total",
                "net_pay_total",
                "updated_at",
            ]
        )


class PayrollEmployeeItem(BaseModel):
    payroll = models.ForeignKey(PayrollRunRecord, on_delete=models.CASCADE, related_name="employee_items")
    employee = models.ForeignKey("hr.Employee", on_delete=models.PROTECT, related_name="payroll_v2_employee_items")
    compensation = models.ForeignKey(
        EmployeeCompensation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_payroll_items",
    )
    basic_salary = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    gross_pay = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    taxable_income = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_tax = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_deductions = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_benefits = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_reimbursements = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    net_pay = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    payment_method = models.CharField(
        max_length=30,
        choices=PaymentMethod.choices,
        default=PaymentMethod.BANK_TRANSFER,
    )
    payment_status = models.CharField(
        max_length=30,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_v2_employee_run_item"
        constraints = [models.UniqueConstraint(fields=["payroll", "employee"], name="payroll_v2_uniq_run_employee")]
        ordering = ["employee__first_name", "employee__last_name"]
        indexes = [
            models.Index(fields=["payroll", "employee"]),
            models.Index(fields=["payment_status"]),
        ]

    def recalculate_totals(self):
        lines = self.line_items.all()
        earnings = sum((l.amount for l in lines if l.line_type == LineType.EARNING), Decimal("0.00"))
        other_deductions = sum((l.amount for l in lines if l.line_type == LineType.DEDUCTION), Decimal("0.00"))
        self.total_tax = sum((l.amount for l in lines if l.line_type == LineType.TAX), Decimal("0.00"))
        self.total_deductions = other_deductions + self.total_tax
        self.total_benefits = sum((l.amount for l in lines if l.line_type == LineType.BENEFIT), Decimal("0.00"))
        self.total_reimbursements = sum(
            (l.amount for l in lines if l.line_type == LineType.REIMBURSEMENT),
            Decimal("0.00"),
        )
        self.gross_pay = earnings
        self.taxable_income = sum((l.amount for l in lines if l.is_taxable), Decimal("0.00"))
        self.net_pay = (
            self.gross_pay
            + self.total_reimbursements
            - self.total_deductions
            - self.total_benefits
        )
        self.save(
            update_fields=[
                "gross_pay",
                "taxable_income",
                "total_tax",
                "total_deductions",
                "total_benefits",
                "total_reimbursements",
                "net_pay",
                "updated_at",
            ]
        )


class PayrollLineItem(BaseModel):
    payroll_employee_item = models.ForeignKey(
        PayrollEmployeeItem,
        on_delete=models.CASCADE,
        related_name="line_items",
    )
    payroll_item = models.ForeignKey(
        PayrollCatalogItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_line_items",
    )
    employee_payroll_item = models.ForeignKey(
        EmployeePayrollItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_line_items",
    )
    payroll_item_rule = models.ForeignKey(
        PayrollCatalogItemRule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_line_items",
    )
    line_type = models.CharField(max_length=30, choices=LineType.choices)
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=50, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    calculation_type = models.CharField(
        max_length=30,
        choices=CalculationType.choices,
        default=CalculationType.FLAT,
    )
    target_amount_source = models.CharField(max_length=50, choices=TargetAmountSource.choices, blank=True)
    is_taxable = models.BooleanField(default=False)
    is_recurring = models.BooleanField(default=False)
    frequency = models.CharField(max_length=30, choices=Frequency.choices, blank=True)
    source_type = models.CharField(max_length=80, blank=True)
    source_id = models.CharField(max_length=80, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_v2_line_item"
        ordering = ["line_type", "name", "id"]
        indexes = [
            models.Index(fields=["payroll_employee_item", "line_type"]),
            models.Index(fields=["payroll_item", "name"]),
        ]


class PayrollSettings(BaseModel):
    """Tenant-level payroll accounting and paystub configuration."""

    transaction_type = models.ForeignKey(
        "accounting.AccountingTransactionType",
        on_delete=models.PROTECT,
        related_name="payroll_settings",
        null=True,
        blank=True,
        help_text="Expense transaction type used when posting payroll cash disbursements.",
    )
    payslip_table_column_labels = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Optional tenant overrides for standard payslip table column headers, e.g. "
            '{"basic": "Base Salary", "tax": "PAYE"}.'
        ),
    )
    show_leave_on_paystub = models.BooleanField(
        default=True,
        help_text="When enabled, eligible leave balances appear on employee paystubs.",
    )

    class Meta:
        db_table = "payroll_settings"
        verbose_name = "Payroll Settings"
        verbose_name_plural = "Payroll Settings"

    def __str__(self):
        return "Payroll Settings"

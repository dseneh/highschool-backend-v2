"""
Tax and expense models.
"""

from django.db import models

from common.models import BaseModel


class AccountingTaxCode(BaseModel):
    """Tax code catalog (VAT, GST, payroll tax, etc.)."""

    class TaxType(models.TextChoices):
        VAT = "vat", "VAT"
        GST = "gst", "GST"
        PAYROLL_TAX = "payroll_tax", "Payroll Tax"
        CORPORATE_TAX = "corporate_tax", "Corporate Tax"
        OTHER = "other", "Other"

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    tax_type = models.CharField(max_length=20, choices=TaxType.choices)
    rate = models.DecimalField(max_digits=5, decimal_places=2, help_text="Tax rate as percentage")
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "accounting_tax_code"
        verbose_name = "Tax Code"
        verbose_name_plural = "Tax Codes"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name} ({self.rate}%)"


class AccountingTaxRemittance(BaseModel):
    """Tax payment remittance record."""

    class RemittanceStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        FILED = "filed", "Filed"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    tax_code = models.ForeignKey(
        AccountingTaxCode,
        on_delete=models.PROTECT,
        related_name="remittances",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=RemittanceStatus.choices, default=RemittanceStatus.PENDING)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2)
    penalty_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_due = models.DecimalField(max_digits=18, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    filing_date = models.DateField(null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True)
    reference_number = models.CharField(max_length=255, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "accounting_tax_remittance"
        verbose_name = "Tax Remittance"
        verbose_name_plural = "Tax Remittances"
        ordering = ["-period_end"]
        unique_together = [["tax_code", "period_start", "period_end"]]

    def __str__(self):
        return f"{self.tax_code.code} - {self.period_start} to {self.period_end}"


class AccountingExpenseRecord(BaseModel):
    """Expense record for non-payroll business expenses."""

    class ExpenseCategory(models.TextChoices):
        SUPPLIES = "supplies", "Supplies"
        UTILITIES = "utilities", "Utilities"
        MAINTENANCE = "maintenance", "Maintenance"
        PROFESSIONAL_FEES = "professional_fees", "Professional Fees"
        TRAVEL = "travel", "Travel"
        OTHER = "other", "Other"

    class ExpenseStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        POSTED = "posted", "Posted"

    category = models.CharField(max_length=30, choices=ExpenseCategory.choices)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    expense_date = models.DateField()
    status = models.CharField(max_length=20, choices=ExpenseStatus.choices, default=ExpenseStatus.DRAFT)
    staff_member = models.ForeignKey(
        "staff.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accounting_expenses",
    )
    reference_number = models.CharField(max_length=255, blank=True, null=True)
    ledger_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.PROTECT,
        related_name="expense_records",
        help_text="Expense account to post to",
    )
    notes = models.TextField(blank=True, null=True)
    submitted_by = models.CharField(max_length=100, blank=True, null=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.CharField(max_length=100, blank=True, null=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounting_expense_record"
        verbose_name = "Expense Record"
        verbose_name_plural = "Expense Records"
        ordering = ["-expense_date"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        return f"{self.description} - {self.amount} ({self.status})"

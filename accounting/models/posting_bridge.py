"""
Payroll posting bridge models for HR-to-Accounting integration.
"""

from django.db import models

from common.models import BaseModel


class AccountingPayrollPostingBatch(BaseModel):
    """Batch of payroll entries posted to journal."""

    class BatchStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        POSTED = "posted", "Posted"
        FAILED = "failed", "Failed"
        REVERSED = "reversed", "Reversed"

    payroll_run = models.ForeignKey(
        "hr.PayrollRun",
        on_delete=models.PROTECT,
        related_name="accounting_posting_batches",
        null=True,
        blank=True,
        help_text="HR payroll run this batch was generated from",
    )
    posting_date = models.DateField()
    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.PROTECT,
    )
    journal_entry = models.ForeignKey(
        "AccountingJournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_posting_batches",
        help_text="Posted journal entry (NULL if not yet posted)",
    )
    batch_status = models.CharField(max_length=20, choices=BatchStatus.choices, default=BatchStatus.PENDING)
    gross_amount = models.DecimalField(max_digits=18, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    idempotent_key = models.CharField(
        max_length=255,
        unique=True,
        help_text="Unique idempotent key to prevent duplicate postings",
    )
    notes = models.TextField(blank=True, null=True)
    posted_by = models.CharField(max_length=100, blank=True, null=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounting_payroll_posting_batch"
        verbose_name = "Payroll Posting Batch"
        verbose_name_plural = "Payroll Posting Batches"
        ordering = ["-posting_date"]
        indexes = [
            models.Index(fields=["idempotent_key"]),
            models.Index(fields=["batch_status"]),
        ]

    def __str__(self):
        return f"Payroll Batch {self.id} - {self.posting_date} ({self.batch_status})"


class AccountingPayrollPostingLine(BaseModel):
    """Individual journal line for a payroll posting batch."""

    class LineType(models.TextChoices):
        SALARY = "salary", "Salary"
        ADVANCE = "advance", "Advance"
        DEDUCTION = "deduction", "Deduction"
        TAX = "tax", "Tax"
        BENEFIT = "benefit", "Benefit"

    posting_batch = models.ForeignKey(
        AccountingPayrollPostingBatch,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    line_type = models.CharField(max_length=20, choices=LineType.choices)
    staff_member = models.ForeignKey(
        "staff.Staff",
        on_delete=models.PROTECT,
        related_name="accounting_payroll_posting_lines",
    )
    debit_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.PROTECT,
        related_name="payroll_posting_debits",
        null=True,
        blank=True,
    )
    credit_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.PROTECT,
        related_name="payroll_posting_credits",
        null=True,
        blank=True,
    )
    debit_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    description = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = "accounting_payroll_posting_line"
        verbose_name = "Payroll Posting Line"
        verbose_name_plural = "Payroll Posting Lines"
        ordering = ["posting_batch", "id"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(debit_amount__gt=0) | models.Q(credit_amount__gt=0),
                name="payroll_posting_line_has_amount",
            ),
        ]

    def __str__(self):
        return f"{self.posting_batch} - {self.staff_member} ({self.line_type})"

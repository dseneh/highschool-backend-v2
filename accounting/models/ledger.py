"""
Core accounting ledger models.
"""

from django.db import models
from decimal import Decimal

from common.models import BaseModel


class AccountingCurrency(BaseModel):
    """Currency used in the tenant's accounting system."""

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=3, unique=True)  # ISO 4217 code
    symbol = models.CharField(max_length=10)
    is_base_currency = models.BooleanField(default=False, help_text="Primary currency for this tenant")
    is_active = models.BooleanField(default=True)
    decimal_places = models.PositiveIntegerField(default=2)

    class Meta:
        db_table = "accounting_currency"
        verbose_name = "Accounting Currency"
        verbose_name_plural = "Accounting Currencies"
        ordering = ["-is_base_currency", "code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class AccountingExchangeRate(BaseModel):
    """Exchange rates between currencies."""

    from_currency = models.ForeignKey(
        AccountingCurrency,
        on_delete=models.PROTECT,
        related_name="rates_from",
    )
    to_currency = models.ForeignKey(
        AccountingCurrency,
        on_delete=models.PROTECT,
        related_name="rates_to",
    )
    rate = models.DecimalField(max_digits=18, decimal_places=8)
    effective_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "accounting_exchange_rate"
        verbose_name = "Accounting Exchange Rate"
        verbose_name_plural = "Accounting Exchange Rates"
        ordering = ["-effective_date"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(rate__gt=Decimal("0")),
                name="exchange_rate_positive",
            ),
        ]

    def __str__(self):
        return f"{self.from_currency.code} -> {self.to_currency.code} @ {self.rate}"


class AccountingLedgerAccount(BaseModel):
    """Chart of accounts: master ledger account definitions."""

    class AccountType(models.TextChoices):
        ASSET = "asset", "Asset"
        LIABILITY = "liability", "Liability"
        EQUITY = "equity", "Equity"
        INCOME = "income", "Income"
        EXPENSE = "expense", "Expense"

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    category = models.CharField(max_length=100, blank=True, help_text="Grouping for reports (e.g., Revenue, COGS)")
    parent_account = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_accounts",
        help_text="Parent account for hierarchical chart structure",
    )
    normal_balance = models.CharField(
        max_length=6,
        choices=[("debit", "Debit"), ("credit", "Credit")],
    )
    is_active = models.BooleanField(default=True)
    is_header = models.BooleanField(default=False, help_text="Header account (no direct postings)")
    is_system_managed = models.BooleanField(
        default=False,
        help_text=(
            "System-managed accounts are seeded/maintained by the platform "
            "(e.g., transfer clearing accounts) and cannot be edited or deleted by users."
        ),
    )
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "accounting_ledger_account"
        verbose_name = "Ledger Account"
        verbose_name_plural = "Ledger Accounts"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                name="accounting_unique_account_code_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class AccountingJournalEntry(BaseModel):
    """Journal entries: grouped set of debits/credits posting to ledger."""

    class EntryStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        POSTED = "posted", "Posted"
        REVERSED = "reversed", "Reversed"

    posting_date = models.DateField()
    reference_number = models.CharField(max_length=100, unique=True)
    source = models.CharField(
        max_length=50,
        choices=[
            ("manual", "Manual"),
            ("student_payment", "Student Payment"),
            ("payroll", "Payroll"),
            ("bank_transfer", "Bank Transfer"),
            ("concession", "Concession"),
            ("fee_adjustment", "Fee Adjustment"),
        ],
    )
    description = models.TextField()
    status = models.CharField(max_length=20, choices=EntryStatus.choices, default=EntryStatus.DRAFT)
    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.PROTECT,
        related_name="accounting_journal_entries",
    )
    posted_by = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="User or system that posted this entry",
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    reversal_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reversals",
    )
    source_reference = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Audit trail: original transaction/document reference",
    )

    class Meta:
        db_table = "accounting_journal_entry"
        verbose_name = "Journal Entry"
        verbose_name_plural = "Journal Entries"
        ordering = ["-posting_date", "-created_at"]
        indexes = [
            models.Index(fields=["posting_date", "status"]),
            models.Index(fields=["reference_number"]),
        ]

    def __str__(self):
        return f"{self.reference_number} - {self.posting_date} - {self.description[:50]}"


class AccountingJournalLine(BaseModel):
    """Individual debit/credit lines within a journal entry."""

    journal_entry = models.ForeignKey(
        AccountingJournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    ledger_account = models.ForeignKey(
        AccountingLedgerAccount,
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )
    currency = models.ForeignKey(
        AccountingCurrency,
        on_delete=models.PROTECT,
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    debit_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Debit amount in transaction currency",
    )
    credit_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Credit amount in transaction currency",
    )
    exchange_rate = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        default=1,
        help_text="Exchange rate to base currency",
    )
    base_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        help_text="Converted amount in base currency",
    )
    description = models.CharField(max_length=255, blank=True)
    line_sequence = models.PositiveIntegerField()

    class Meta:
        db_table = "accounting_journal_line"
        verbose_name = "Journal Line"
        verbose_name_plural = "Journal Lines"
        ordering = ["journal_entry", "line_sequence"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(debit_amount__gte=0, credit_amount__gte=0),
                name="journal_line_non_negative_amounts",
            ),
        ]

    def __str__(self):
        return f"{self.journal_entry.reference_number} - Line {self.line_sequence}"

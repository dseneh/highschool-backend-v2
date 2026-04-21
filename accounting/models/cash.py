"""
Cash and banking models.
"""

from django.db import models

from common.models import BaseModel


class AccountingPaymentMethod(BaseModel):
    """Payment method types (Cash, Check, Bank Transfer, etc.)."""

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "accounting_payment_method"
        verbose_name = "Payment Method"
        verbose_name_plural = "Payment Methods"
        ordering = ["name"]

    def __str__(self):
        return self.name


class AccountingTransactionType(BaseModel):
    """Transaction type classification (Invoice, Payment, Refund, Transfer, etc.)."""

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    transaction_category = models.CharField(
        max_length=20,
        choices=[
            ("income", "Income"),
            ("expense", "Expense"),
            ("transfer", "Transfer"),
        ],
    )
    description = models.TextField(blank=True, null=True)
    default_ledger_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_transaction_types",
        help_text="Default income/expense ledger account used for auto-posting",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "accounting_transaction_type"
        verbose_name = "Transaction Type"
        verbose_name_plural = "Transaction Types"
        ordering = ["name"]

    def __str__(self):
        return self.name


class AccountingBankAccount(BaseModel):
    """Bank account and cash accounts."""

    class AccountStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        CLOSED = "closed", "Closed"

    account_number = models.CharField(max_length=50, unique=True)
    account_name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255, blank=True)
    account_type = models.CharField(
        max_length=20,
        choices=[
            ("checking", "Checking"),
            ("savings", "Savings"),
            ("cash", "Cash"),
            ("other", "Other"),
        ],
    )
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    ledger_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_accounts",
        help_text="Ledger cash/bank account used during posting",
    )
    opening_balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    opening_balance_date = models.DateField(null=True, blank=True)
    current_balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Calculated from approved transactions",
    )
    status = models.CharField(max_length=20, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "accounting_bank_account"
        verbose_name = "Bank Account"
        verbose_name_plural = "Bank Accounts"
        ordering = ["account_number"]

    def __str__(self):
        return f"{self.account_name} ({self.account_number})"


class AccountingCashTransaction(BaseModel):
    """Cash transactions: payments received, expenses paid, transfers."""

    class TransactionStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    bank_account = models.ForeignKey(
        AccountingBankAccount,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    transaction_date = models.DateField()
    reference_number = models.CharField(max_length=100, unique=True)
    transaction_type = models.ForeignKey(
        AccountingTransactionType,
        on_delete=models.PROTECT,
    )
    payment_method = models.ForeignKey(
        AccountingPaymentMethod,
        on_delete=models.PROTECT,
    )
    ledger_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_transactions",
        help_text="Optional override account; if empty, use transaction type default",
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
    )
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=8, default=1)
    base_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        help_text="Amount in base currency",
    )
    payer_payee = models.CharField(max_length=255, blank=True, help_text="Who paid/received")
    description = models.TextField()
    status = models.CharField(max_length=20, choices=TransactionStatus.choices, default=TransactionStatus.PENDING)
    approved_by = models.CharField(max_length=100, blank=True, null=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    source_reference = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Audit trail: original document/invoice reference",
    )
    journal_entry = models.ForeignKey(
        "AccountingJournalEntry",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cash_transactions",
        help_text="Posted journal entry — deleting the journal entry also deletes this transaction",
    )

    class Meta:
        db_table = "accounting_cash_transaction"
        verbose_name = "Cash Transaction"
        verbose_name_plural = "Cash Transactions"
        ordering = ["-transaction_date", "-created_at"]
        indexes = [
            models.Index(fields=["transaction_date", "status"]),
            models.Index(fields=["bank_account", "status"]),
            models.Index(fields=["transaction_type", "status"]),
        ]

    def __str__(self):
        return f"{self.reference_number} - {self.transaction_date} - {self.amount}"


class AccountingAccountTransfer(BaseModel):
    """Explicit transfers between bank accounts."""

    class TransferStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    transfer_date = models.DateField()
    reference_number = models.CharField(max_length=100, unique=True)
    from_account = models.ForeignKey(
        AccountingBankAccount,
        on_delete=models.PROTECT,
        related_name="transfers_from",
    )
    to_account = models.ForeignKey(
        AccountingBankAccount,
        on_delete=models.PROTECT,
        related_name="transfers_to",
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    from_currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
        related_name="transfers_from_currency",
    )
    to_currency = models.ForeignKey(
        "AccountingCurrency",
        on_delete=models.PROTECT,
        related_name="transfers_to_currency",
    )
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=8, default=1)
    to_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        help_text="Amount received in to_currency",
    )
    status = models.CharField(max_length=20, choices=TransferStatus.choices, default=TransferStatus.PENDING)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "accounting_account_transfer"
        verbose_name = "Account Transfer"
        verbose_name_plural = "Account Transfers"
        ordering = ["-transfer_date"]

    def __str__(self):
        return f"{self.reference_number} - {self.transfer_date}"

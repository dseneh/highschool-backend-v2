"""Bank-account rule configuration for balance limits and spend allocations."""

from decimal import Decimal

from django.db import models

from common.models import BaseModel


class AccountingRevenuePeriod(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    YEARLY = "yearly", "Yearly"
    ALL_TIME = "all_time", "All Time"


class AccountingLimitMode(models.TextChoices):
    FIXED_AMOUNT = "fixed_amount", "Fixed Amount"
    PERCENT_REVENUE = "percent_revenue", "Percentage of Total Revenue"


class AccountingLimitBehavior(models.TextChoices):
    BLOCK = "block", "Block Transaction"
    WARN = "warn", "Allow with Warning"


class AccountingAlertTrigger(models.TextChoices):
    BEFORE = "before", "Before Maximum"
    AT_MAXIMUM = "at_maximum", "At Maximum"
    BOTH = "both", "Before and At Maximum"


class AccountingNotificationTriggerStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    COMPLETED = "completed", "Completed"


class AccountingNotificationChannel(models.TextChoices):
    IN_APP = "in_app", "In-App"
    EMAIL = "email", "Email"
    BOTH = "both", "Both"


class AccountingBankBalanceRule(BaseModel):
    """Configurable max-balance rule for one or more bank accounts."""

    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    bank_accounts = models.ManyToManyField(
        "AccountingBankAccount",
        related_name="balance_rules",
        blank=True,
    )

    limit_mode = models.CharField(
        max_length=32,
        choices=AccountingLimitMode.choices,
        default=AccountingLimitMode.FIXED_AMOUNT,
    )
    fixed_maximum_balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    revenue_percentage = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Percentage of total revenue when limit_mode=percent_revenue.",
    )
    revenue_period = models.CharField(
        max_length=32,
        choices=AccountingRevenuePeriod.choices,
        default=AccountingRevenuePeriod.MONTHLY,
    )

    behavior = models.CharField(
        max_length=16,
        choices=AccountingLimitBehavior.choices,
        default=AccountingLimitBehavior.BLOCK,
    )

    enable_email_alerts = models.BooleanField(default=False)
    alert_trigger = models.CharField(
        max_length=24,
        choices=AccountingAlertTrigger.choices,
        default=AccountingAlertTrigger.BOTH,
    )
    notification_trigger_status = models.CharField(
        max_length=16,
        choices=AccountingNotificationTriggerStatus.choices,
        default=AccountingNotificationTriggerStatus.COMPLETED,
    )
    notification_channel = models.CharField(
        max_length=16,
        choices=AccountingNotificationChannel.choices,
        default=AccountingNotificationChannel.IN_APP,
    )
    alert_threshold_percentage = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("90.00"),
    )
    alert_recipients = models.ManyToManyField(
        "hr.Employee",
        related_name="accounting_balance_alert_rules",
        blank=True,
    )

    use_default_email_template = models.BooleanField(default=True)
    email_subject_template = models.TextField(blank=True, default="")
    email_body_template = models.TextField(blank=True, default="")

    class Meta:
        db_table = "accounting_bank_balance_rule"
        verbose_name = "Accounting Bank Balance Rule"
        verbose_name_plural = "Accounting Bank Balance Rules"
        ordering = ["name", "created_at"]

    def __str__(self):
        return self.name


class AccountingSpendableAllocationRule(BaseModel):
    """Optional cap for spendable allocations based on fixed/percent of revenue."""

    name = models.CharField(max_length=150, default="Spendable Allocation")
    is_active = models.BooleanField(default=False)

    limit_mode = models.CharField(
        max_length=32,
        choices=AccountingLimitMode.choices,
        default=AccountingLimitMode.FIXED_AMOUNT,
    )
    fixed_allocation = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    revenue_percentage = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
    )
    revenue_period = models.CharField(
        max_length=32,
        choices=AccountingRevenuePeriod.choices,
        default=AccountingRevenuePeriod.MONTHLY,
    )

    behavior = models.CharField(
        max_length=16,
        choices=AccountingLimitBehavior.choices,
        default=AccountingLimitBehavior.BLOCK,
    )

    class Meta:
        db_table = "accounting_spendable_allocation_rule"
        verbose_name = "Accounting Spendable Allocation Rule"
        verbose_name_plural = "Accounting Spendable Allocation Rules"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class AccountingRuleThresholdState(BaseModel):
    """State machine row used to suppress duplicate threshold alerts."""

    balance_rule = models.ForeignKey(
        AccountingBankBalanceRule,
        on_delete=models.CASCADE,
        related_name="threshold_states",
    )
    bank_account = models.ForeignKey(
        "AccountingBankAccount",
        on_delete=models.CASCADE,
        related_name="threshold_states",
    )
    threshold_percentage = models.DecimalField(max_digits=7, decimal_places=2)
    is_above_threshold = models.BooleanField(default=False)
    last_triggered_balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    last_notified_event_key = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        db_table = "accounting_rule_threshold_state"
        verbose_name = "Accounting Rule Threshold State"
        verbose_name_plural = "Accounting Rule Threshold States"
        unique_together = ("balance_rule", "bank_account", "threshold_percentage")
        indexes = [
            models.Index(fields=["balance_rule", "bank_account"]),
            models.Index(fields=["last_triggered_at"]),
        ]

    def __str__(self):
        return (
            f"{self.balance_rule.name} | {self.bank_account.account_name}"
            f" | {self.threshold_percentage}%"
        )

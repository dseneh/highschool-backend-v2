"""Tenant-level accounting configuration."""

from django.db import models

from common.models import BaseModel


class AccountingSettings(BaseModel):
    """Singleton-style settings for GL mappings used by transfers and payroll posting."""

    transfer_in_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.PROTECT,
        related_name="accounting_settings_transfer_in",
        null=True,
        blank=True,
        help_text="Asset account used as the counterparty for TRANSFER_IN postings.",
    )
    transfer_out_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.PROTECT,
        related_name="accounting_settings_transfer_out",
        null=True,
        blank=True,
        help_text="Asset account used as the counterparty for TRANSFER_OUT postings.",
    )
    salary_expense_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.PROTECT,
        related_name="accounting_settings_salary_expense",
        null=True,
        blank=True,
        help_text="Expense account debited when payroll is posted to the ledger.",
    )
    payroll_tax_payable_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.PROTECT,
        related_name="accounting_settings_payroll_tax_payable",
        null=True,
        blank=True,
        help_text="Liability account credited for payroll tax withholdings.",
    )
    payroll_deductions_payable_account = models.ForeignKey(
        "AccountingLedgerAccount",
        on_delete=models.PROTECT,
        related_name="accounting_settings_payroll_deductions_payable",
        null=True,
        blank=True,
        help_text="Liability account credited for non-tax payroll deductions.",
    )

    class Meta:
        db_table = "accounting_settings"
        verbose_name = "Accounting Settings"
        verbose_name_plural = "Accounting Settings"

    def __str__(self):
        return "Accounting Settings"

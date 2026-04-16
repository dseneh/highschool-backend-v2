"""
Accounting models for the school management system.

All models are tenant-specific (live in tenant schemas).
"""

from .ledger import (
    AccountingCurrency,
    AccountingExchangeRate,
    AccountingLedgerAccount,
    AccountingJournalEntry,
    AccountingJournalLine,
)
from .cash import (
    AccountingBankAccount,
    AccountingPaymentMethod,
    AccountingTransactionType,
    AccountingCashTransaction,
    AccountingAccountTransfer,
)
from .receivables import (
    AccountingFeeItem,
    AccountingFeeRate,
    AccountingStudentBill,
    AccountingStudentBillLine,
    AccountingConcession,
    AccountingInstallmentPlan,
    AccountingInstallmentLine,
    AccountingStudentPaymentAllocation,
    AccountingARSnapshot,
)
from .tax_expense import (
    AccountingTaxCode,
    AccountingTaxRemittance,
    AccountingExpenseRecord,
)
from .posting_bridge import (
    AccountingPayrollPostingBatch,
    AccountingPayrollPostingLine,
)

__all__ = [
    # Ledger
    "AccountingCurrency",
    "AccountingExchangeRate",
    "AccountingLedgerAccount",
    "AccountingJournalEntry",
    "AccountingJournalLine",
    # Cash
    "AccountingBankAccount",
    "AccountingPaymentMethod",
    "AccountingTransactionType",
    "AccountingCashTransaction",
    "AccountingAccountTransfer",
    # Receivables
    "AccountingFeeItem",
    "AccountingFeeRate",
    "AccountingStudentBill",
    "AccountingStudentBillLine",
    "AccountingConcession",
    "AccountingInstallmentPlan",
    "AccountingInstallmentLine",
    "AccountingStudentPaymentAllocation",
    "AccountingARSnapshot",
    # Tax/Expense
    "AccountingTaxCode",
    "AccountingTaxRemittance",
    "AccountingExpenseRecord",
    # Posting Bridge
    "AccountingPayrollPostingBatch",
    "AccountingPayrollPostingLine",
]

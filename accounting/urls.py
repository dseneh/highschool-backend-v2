from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounting.views import (
    AccountingARSnapshotViewSet,
    AccountingAccountTransferViewSet,
    AccountingBankAccountViewSet,
    AccountingConcessionViewSet,
    AccountingCurrencyViewSet,
    AccountingCashTransactionViewSet,
    AccountingExchangeRateViewSet,
    AccountingExpenseRecordViewSet,
    AccountingFeeRateViewSet,
    AccountingInstallmentLineViewSet,
    AccountingInstallmentPlanViewSet,
    AccountingJournalEntryViewSet,
    AccountingJournalLineViewSet,
    AccountingLedgerAccountViewSet,
    AccountingPaymentMethodViewSet,
    AccountingPayrollPostingBatchViewSet,
    AccountingPayrollPostingLineViewSet,
    AccountingStudentBillLineViewSet,
    AccountingStudentBillViewSet,
    AccountingStudentPaymentAllocationViewSet,
    AccountingTaxCodeViewSet,
    AccountingTaxRemittanceViewSet,
    AccountingTransactionTypeViewSet,
)

router = DefaultRouter()
router.register(r"accounting/currencies", AccountingCurrencyViewSet, basename="accounting-currency")
router.register(r"accounting/exchange-rates", AccountingExchangeRateViewSet, basename="accounting-exchange-rate")
router.register(r"accounting/ledger-accounts", AccountingLedgerAccountViewSet, basename="accounting-ledger-account")
router.register(r"accounting/journal-entries", AccountingJournalEntryViewSet, basename="accounting-journal-entry")
router.register(r"accounting/journal-lines", AccountingJournalLineViewSet, basename="accounting-journal-line")
router.register(r"accounting/cash-transactions", AccountingCashTransactionViewSet, basename="accounting-cash-transaction")
router.register(r"accounting/account-transfers", AccountingAccountTransferViewSet, basename="accounting-account-transfer")
router.register(r"accounting/transaction-types", AccountingTransactionTypeViewSet, basename="accounting-transaction-type")
router.register(r"accounting/payment-methods", AccountingPaymentMethodViewSet, basename="accounting-payment-method")
router.register(r"accounting/bank-accounts", AccountingBankAccountViewSet, basename="accounting-bank-account")
router.register(r"accounting/fee-rates", AccountingFeeRateViewSet, basename="accounting-fee-rate")
router.register(r"accounting/student-bills", AccountingStudentBillViewSet, basename="accounting-student-bill")
router.register(r"accounting/student-bill-lines", AccountingStudentBillLineViewSet, basename="accounting-student-bill-line")
router.register(r"accounting/concessions", AccountingConcessionViewSet, basename="accounting-concession")
router.register(r"accounting/installment-plans", AccountingInstallmentPlanViewSet, basename="accounting-installment-plan")
router.register(r"accounting/installment-lines", AccountingInstallmentLineViewSet, basename="accounting-installment-line")
router.register(r"accounting/payment-allocations", AccountingStudentPaymentAllocationViewSet, basename="accounting-payment-allocation")
router.register(r"accounting/ar-snapshots", AccountingARSnapshotViewSet, basename="accounting-ar-snapshot")
router.register(r"accounting/tax-codes", AccountingTaxCodeViewSet, basename="accounting-tax-code")
router.register(r"accounting/tax-remittances", AccountingTaxRemittanceViewSet, basename="accounting-tax-remittance")
router.register(r"accounting/expense-records", AccountingExpenseRecordViewSet, basename="accounting-expense-record")
router.register(r"accounting/payroll-posting-batches", AccountingPayrollPostingBatchViewSet, basename="accounting-payroll-posting-batch")
router.register(r"accounting/payroll-posting-lines", AccountingPayrollPostingLineViewSet, basename="accounting-payroll-posting-line")

urlpatterns = [
    path("", include(router.urls)),
]

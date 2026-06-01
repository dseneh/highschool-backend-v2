"""
Reports URL Configuration

URL patterns for the reports app including:
- Transaction reports
- Export status monitoring
- Student reports
- Finance reports
- Accounting, payroll, attendance, academic, and HR reports
"""

from django.urls import path

from .views.transactions import (
    TransactionReportView,
    TransactionExportStatusView,
    TransactionReportDownloadView,
)
from .views.students import StudentReportView, StudentIndividualReportView
from .views.finance import FinanceReportView
from .views.student_payment_detail import StudentPaymentDetailReportView
from .views.accounting_summary import AccountingSummaryReportView
from .views.ar_reports import (
    ARAgingReportView,
    InstallmentComplianceReportView,
    ConcessionSummaryReportView,
    CollectionRateReportView,
    PaymentAllocationReportView,
)
from .views.gl_reports import (
    JournalRegisterReportView,
    TrialBalanceReportView,
    PendingTransactionsReportView,
    ChartOfAccountsReportView,
)
from .views.banking_reports import BankBalanceSummaryReportView, BankReconciliationReportView
from .views.payroll_reports import (
    PayrollRunSummaryReportView,
    PayrollRegisterReportView,
    PayrollPostingJournalReportView,
)
from .views.attendance_reports import AttendanceSummaryReportView, DailyAttendanceRegisterReportView
from .views.academic_reports import ClassGradeSummaryReportView, HonorRollReportView
from .views.report_cards import BulkReportCardsExportView
from .views.hr_reports import EmployeeListReportView, StaffDirectoryReportView
from .views.advanced_reports import ProfitLossReportView, RevenueReportView, CustomReportBuilderView

app_name = "reports"

urlpatterns = [
    # Legacy transaction reports (deprecated — prefer accounting/cash-transactions/export/)
    path("transactions/", TransactionReportView.as_view(), name="transaction-reports"),
    # Student Reports
    path("students/", StudentReportView.as_view(), name="student-reports"),
    path("students/<str:student_id>/", StudentIndividualReportView.as_view(), name="student-individual-reports"),
    # Finance / AR Reports
    path("finance/", FinanceReportView.as_view(), name="finance-reports"),
    path("finance/student-payments/", StudentPaymentDetailReportView.as_view(), name="student-payment-detail-reports"),
    path("finance/ar-aging/", ARAgingReportView.as_view(), name="ar-aging-reports"),
    path("finance/installment-compliance/", InstallmentComplianceReportView.as_view(), name="installment-compliance-reports"),
    path("finance/concession-summary/", ConcessionSummaryReportView.as_view(), name="concession-summary-reports"),
    path("finance/collection-rate/", CollectionRateReportView.as_view(), name="collection-rate-reports"),
    path("finance/payment-allocations/", PaymentAllocationReportView.as_view(), name="payment-allocation-reports"),
    # Accounting Reports
    path("accounting-summary/", AccountingSummaryReportView.as_view(), name="accounting-summary-reports"),
    path("accounting/journal-register/", JournalRegisterReportView.as_view(), name="journal-register-reports"),
    path("accounting/trial-balance/", TrialBalanceReportView.as_view(), name="trial-balance-reports"),
    path("accounting/pending-transactions/", PendingTransactionsReportView.as_view(), name="pending-transactions-reports"),
    path("accounting/chart-of-accounts/", ChartOfAccountsReportView.as_view(), name="chart-of-accounts-reports"),
    path("accounting/bank-balances/", BankBalanceSummaryReportView.as_view(), name="bank-balance-reports"),
    path("accounting/bank-reconciliation/", BankReconciliationReportView.as_view(), name="bank-reconciliation-reports"),
    path("accounting/profit-loss/", ProfitLossReportView.as_view(), name="profit-loss-reports"),
    path("accounting/revenue/", RevenueReportView.as_view(), name="revenue-reports"),
    # Payroll Reports
    path("payroll/run-summary/", PayrollRunSummaryReportView.as_view(), name="payroll-run-summary-reports"),
    path("payroll/register/", PayrollRegisterReportView.as_view(), name="payroll-register-reports"),
    path("payroll/posting-journal/", PayrollPostingJournalReportView.as_view(), name="payroll-posting-journal-reports"),
    # Attendance Reports
    path("attendance/summary/", AttendanceSummaryReportView.as_view(), name="attendance-summary-reports"),
    path("attendance/daily/", DailyAttendanceRegisterReportView.as_view(), name="attendance-daily-reports"),
    # Academic Reports
    path("academics/grade-summary/", ClassGradeSummaryReportView.as_view(), name="class-grade-summary-reports"),
    path("academics/honor-roll/", HonorRollReportView.as_view(), name="honor-roll-reports"),
    path(
        "academics/report-cards/",
        BulkReportCardsExportView.as_view(),
        name="bulk-report-cards",
    ),
    # HR Reports
    path("hr/employees/", EmployeeListReportView.as_view(), name="employee-list-reports"),
    path("hr/staff-directory/", StaffDirectoryReportView.as_view(), name="staff-directory-reports"),
    # Custom report builder metadata
    path("custom-builder/", CustomReportBuilderView.as_view(), name="custom-report-builder"),
    # Export Status Management
    path("export-status/<str:task_id>/", TransactionExportStatusView.as_view(), name="export-status"),
    # Download Results
    path("download/<str:task_id>/", TransactionReportDownloadView.as_view(), name="download-report"),
]

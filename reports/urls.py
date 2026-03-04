"""
Reports URL Configuration

URL patterns for the reports app including:
- Transaction reports
- Export status monitoring
- Student reports
- Finance reports
"""

from django.urls import path

from .views.transactions import (
    TransactionReportView, 
    TransactionExportStatusView,
    TransactionReportDownloadView
)
from .views.students import StudentReportView
from .views.finance import FinanceReportView

app_name = 'reports'

urlpatterns = [
    # Transaction Reports
    path('transactions/', TransactionReportView.as_view(), name='transaction-reports'),
    
    # Student Reports
    path('students/', StudentReportView.as_view(), name='student-reports'),
    
    # Finance Reports
    path('finance/', FinanceReportView.as_view(), name='finance-reports'),
    
    # Export Status Management
    path('export-status/<str:task_id>/', TransactionExportStatusView.as_view(), name='export-status'),
    
    # Download Results
    path('download/<str:task_id>/', TransactionReportDownloadView.as_view(), name='download-report'),
]

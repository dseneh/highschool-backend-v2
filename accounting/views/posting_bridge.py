from rest_framework import viewsets

from accounting.access_policies import AccountingFinanceAccessPolicy
from accounting.models import AccountingPayrollPostingBatch, AccountingPayrollPostingLine
from accounting.serializers import (
    AccountingPayrollPostingBatchSerializer,
    AccountingPayrollPostingLineSerializer,
)
from accounting.views.base import AccountingErrorFormattingMixin


class AccountingPayrollPostingBatchViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingPayrollPostingBatch.objects.select_related(
        "payroll_run",
        "academic_year",
        "journal_entry",
        "currency",
    ).order_by("-posting_date", "-created_at")
    serializer_class = AccountingPayrollPostingBatchSerializer
    permission_classes = [AccountingFinanceAccessPolicy]


class AccountingPayrollPostingLineViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingPayrollPostingLine.objects.select_related(
        "posting_batch",
        "staff_member",
        "debit_account",
        "credit_account",
        "currency",
    ).order_by("posting_batch", "id")
    serializer_class = AccountingPayrollPostingLineSerializer
    permission_classes = [AccountingFinanceAccessPolicy]

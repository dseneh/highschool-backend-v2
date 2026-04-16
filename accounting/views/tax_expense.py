from rest_framework import viewsets

from accounting.access_policies import AccountingFinanceAccessPolicy
from accounting.models import (
    AccountingExpenseRecord,
    AccountingTaxCode,
    AccountingTaxRemittance,
)
from accounting.serializers import (
    AccountingExpenseRecordSerializer,
    AccountingTaxCodeSerializer,
    AccountingTaxRemittanceSerializer,
)
from accounting.views.base import AccountingErrorFormattingMixin


class AccountingTaxCodeViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingTaxCode.objects.order_by("code")
    serializer_class = AccountingTaxCodeSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None


class AccountingTaxRemittanceViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingTaxRemittance.objects.select_related("tax_code", "currency").order_by("-period_end")
    serializer_class = AccountingTaxRemittanceSerializer
    permission_classes = [AccountingFinanceAccessPolicy]

    def get_queryset(self):
        queryset = super().get_queryset()
        tax_code = self.request.query_params.get("tax_code")
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if tax_code:
            queryset = queryset.filter(tax_code_id=tax_code)
        if start_date:
            queryset = queryset.filter(period_end__gte=start_date)
        if end_date:
            queryset = queryset.filter(period_end__lte=end_date)

        return queryset


class AccountingExpenseRecordViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingExpenseRecord.objects.select_related(
        "currency",
        "staff_member",
        "ledger_account",
    ).order_by("-expense_date", "-created_at")
    serializer_class = AccountingExpenseRecordSerializer
    permission_classes = [AccountingFinanceAccessPolicy]

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get("status")
        staff_member = self.request.query_params.get("staff_member")
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if status_param:
            queryset = queryset.filter(status=status_param)
        if staff_member:
            queryset = queryset.filter(staff_member_id=staff_member)
        if start_date:
            queryset = queryset.filter(expense_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(expense_date__lte=end_date)

        return queryset

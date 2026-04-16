from rest_framework import viewsets

from accounting.access_policies import AccountingFinanceAccessPolicy
from accounting.models import (
    AccountingARSnapshot,
    AccountingConcession,
    AccountingFeeItem,
    AccountingFeeRate,
    AccountingInstallmentLine,
    AccountingInstallmentPlan,
    AccountingStudentBill,
    AccountingStudentBillLine,
    AccountingStudentPaymentAllocation,
)
from accounting.serializers import (
    AccountingARSnapshotSerializer,
    AccountingConcessionSerializer,
    AccountingFeeItemSerializer,
    AccountingFeeRateSerializer,
    AccountingInstallmentLineSerializer,
    AccountingInstallmentPlanSerializer,
    AccountingStudentBillLineSerializer,
    AccountingStudentBillSerializer,
    AccountingStudentPaymentAllocationSerializer,
)
from accounting.views.base import AccountingErrorFormattingMixin


class AccountingFeeItemViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingFeeItem.objects.order_by("code")
    serializer_class = AccountingFeeItemSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None


class AccountingFeeRateViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingFeeRate.objects.select_related("fee_item", "academic_year", "grade_level", "currency").order_by("academic_year", "fee_item")
    serializer_class = AccountingFeeRateSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None


class AccountingStudentBillViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingStudentBill.objects.select_related("enrollment", "academic_year", "student", "grade_level", "currency").order_by("-bill_date", "-created_at")
    serializer_class = AccountingStudentBillSerializer
    permission_classes = [AccountingFinanceAccessPolicy]

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get("status")
        academic_year = self.request.query_params.get("academic_year")
        student = self.request.query_params.get("student")
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if status_param:
            queryset = queryset.filter(status=status_param)
        if academic_year:
            queryset = queryset.filter(academic_year_id=academic_year)
        if student:
            queryset = queryset.filter(student_id=student)
        if start_date:
            queryset = queryset.filter(bill_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(bill_date__lte=end_date)

        return queryset


class AccountingStudentBillLineViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingStudentBillLine.objects.select_related("student_bill", "fee_item", "currency").order_by("student_bill", "line_sequence")
    serializer_class = AccountingStudentBillLineSerializer
    permission_classes = [AccountingFinanceAccessPolicy]


class AccountingConcessionViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingConcession.objects.select_related("student", "student_bill", "academic_year", "currency").order_by("-start_date")
    serializer_class = AccountingConcessionSerializer
    permission_classes = [AccountingFinanceAccessPolicy]


class AccountingInstallmentPlanViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingInstallmentPlan.objects.select_related("academic_year").order_by("academic_year", "name")
    serializer_class = AccountingInstallmentPlanSerializer
    permission_classes = [AccountingFinanceAccessPolicy]


class AccountingInstallmentLineViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingInstallmentLine.objects.select_related("installment_plan").order_by("installment_plan", "sequence")
    serializer_class = AccountingInstallmentLineSerializer
    permission_classes = [AccountingFinanceAccessPolicy]


class AccountingStudentPaymentAllocationViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingStudentPaymentAllocation.objects.select_related(
        "student_bill",
        "cash_transaction",
        "installment_line",
        "currency",
    ).order_by("-allocation_date", "-created_at")
    serializer_class = AccountingStudentPaymentAllocationSerializer
    permission_classes = [AccountingFinanceAccessPolicy]


class AccountingARSnapshotViewSet(AccountingErrorFormattingMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AccountingARSnapshot.objects.select_related("student", "academic_year", "currency").order_by("-last_updated")
    serializer_class = AccountingARSnapshotSerializer
    permission_classes = [AccountingFinanceAccessPolicy]

    def get_queryset(self):
        queryset = super().get_queryset()
        academic_year = self.request.query_params.get("academic_year")
        student = self.request.query_params.get("student")
        payment_status = self.request.query_params.get("payment_status")

        if academic_year:
            queryset = queryset.filter(academic_year_id=academic_year)
        if student:
            queryset = queryset.filter(student_id=student)
        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)

        return queryset

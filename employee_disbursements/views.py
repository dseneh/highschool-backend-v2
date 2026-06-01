from datetime import date

from django.db.models import Sum
from django_filters import rest_framework as filters
from rest_framework import filters as drf_filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from employee_disbursements.access_policies import EmployeeDisbursementsAccessPolicy
from employee_disbursements.enums import DisbursementRecordStatus, DisbursementSourceType
from employee_disbursements.models import EmployeeDisbursementRecord
from employee_disbursements.portal_access import apply_employee_portal_disbursement_filters
from employee_disbursements.serializers import (
    EmployeeDisbursementRecordDetailSerializer,
    EmployeeDisbursementRecordListSerializer,
)


class EmployeeDisbursementRecordFilter(filters.FilterSet):
    employee = filters.UUIDFilter(field_name="employee_id")
    source_type = filters.CharFilter(field_name="source_type")
    status = filters.CharFilter(field_name="status")
    payment_date_after = filters.DateFilter(field_name="payment_date", lookup_expr="gte")
    payment_date_before = filters.DateFilter(field_name="payment_date", lookup_expr="lte")
    year = filters.NumberFilter(method="filter_year")

    class Meta:
        model = EmployeeDisbursementRecord
        fields = ["employee", "source_type", "status", "payment_date_after", "payment_date_before", "year"]

    def filter_year(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(payment_date__year=value)


class EmployeeDisbursementRecordViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [EmployeeDisbursementsAccessPolicy]
    filter_backends = [filters.DjangoFilterBackend, drf_filters.OrderingFilter, drf_filters.SearchFilter]
    filterset_class = EmployeeDisbursementRecordFilter
    search_fields = ["title", "reference_number", "benefit_type_name"]
    ordering_fields = ["payment_date", "paid_at", "net_amount", "created_at"]
    ordering = ["-payment_date", "-paid_at"]

    def get_queryset(self):
        qs = EmployeeDisbursementRecord.objects.select_related(
            "employee",
            "employee__department",
            "employee__position",
            "currency",
        )
        qs = apply_employee_portal_disbursement_filters(qs, self.request.user)

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        elif not self.request.query_params.get("include_reverted"):
            qs = qs.filter(status=DisbursementRecordStatus.ACTIVE)

        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return EmployeeDisbursementRecordDetailSerializer
        return EmployeeDisbursementRecordListSerializer

    @action(detail=False, methods=["get"], url_path="ytd")
    def ytd(self, request):
        employee_id = request.query_params.get("employee")
        year_param = request.query_params.get("year")
        source_type = request.query_params.get("source_type")

        if not employee_id:
            return Response({"detail": "employee query parameter is required."}, status=400)

        try:
            year = int(year_param) if year_param else date.today().year
        except (TypeError, ValueError):
            return Response({"detail": "Invalid year."}, status=400)

        qs = self.get_queryset().filter(
            employee_id=employee_id,
            status=DisbursementRecordStatus.ACTIVE,
            payment_date__year=year,
        )
        if source_type:
            qs = qs.filter(source_type=source_type)

        payroll_net = qs.filter(source_type=DisbursementSourceType.PAYROLL).aggregate(
            total=Sum("net_amount")
        )["total"]
        benefit_net = qs.filter(source_type=DisbursementSourceType.BENEFIT).aggregate(
            total=Sum("net_amount")
        )["total"]

        benefit_by_type = (
            qs.filter(source_type=DisbursementSourceType.BENEFIT)
            .values("benefit_type_name")
            .annotate(total=Sum("net_amount"))
            .order_by("benefit_type_name")
        )

        return Response(
            {
                "employee": employee_id,
                "year": year,
                "payroll_net": payroll_net or 0,
                "benefit_net": benefit_net or 0,
                "total_net": (payroll_net or 0) + (benefit_net or 0),
                "benefit_by_type": list(benefit_by_type),
            }
        )

from django.db.models import Count
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .access_policies import EmployeeBenefitsAccessPolicy
from .enums import BenefitRequestStatus
from .models import (
    BenefitRequest,
    BenefitRequestLine,
    BenefitSettings,
    BenefitType,
    BenefitTypeRule,
    EmployeeBenefit,
)
from .portal_access import apply_employee_portal_benefit_filters
from .serializers import (
    BenefitRequestDetailSerializer,
    BenefitRequestLineSerializer,
    BenefitRequestListSerializer,
    BenefitRequestWriteSerializer,
    BenefitSettingsSerializer,
    BenefitTypeRuleSerializer,
    BenefitTypeSerializer,
    EmployeeBenefitSerializer,
    GenerateBenefitRequestSerializer,
    SyncBenefitEmployeesSerializer,
)
from .permissions import require_manage_employee_benefit_assignments
from .services import (
    approve_benefit_request,
    cancel_benefit_request,
    generate_benefit_request,
    mark_benefit_request_paid,
    remove_benefit_type_from_employees,
    revert_benefit_request_to_draft,
    revert_employee_benefit_calculation,
    submit_benefit_request_for_approval,
    sync_benefit_type_to_employees,
)
from .settings_services import get_tenant_benefit_settings


class BaseBenefitViewSet(viewsets.ModelViewSet):
    permission_classes = [EmployeeBenefitsAccessPolicy]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class BenefitTypeViewSet(BaseBenefitViewSet):
    queryset = BenefitType.objects.annotate(
        employee_count=Count("employee_assignments", distinct=True)
    ).prefetch_related("rules")
    serializer_class = BenefitTypeSerializer
    search_fields = ["name", "code"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    @action(detail=True, methods=["post"], url_path="sync-employees")
    def sync_employees(self, request, pk=None):
        benefit_type = self.get_object()
        serializer = SyncBenefitEmployeesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = sync_benefit_type_to_employees(
                benefit_type=benefit_type,
                scope=serializer.validated_data["scope"],
                employee_ids=serializer.validated_data.get("employee_ids"),
                department_id=serializer.validated_data.get("department_id"),
                position_id=serializer.validated_data.get("position_id"),
                actor=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    @action(detail=True, methods=["post"], url_path="remove-from-employees")
    def remove_from_employees(self, request, pk=None):
        benefit_type = self.get_object()
        serializer = SyncBenefitEmployeesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = remove_benefit_type_from_employees(
                benefit_type=benefit_type,
                scope=serializer.validated_data["scope"],
                employee_ids=serializer.validated_data.get("employee_ids"),
                department_id=serializer.validated_data.get("department_id"),
                position_id=serializer.validated_data.get("position_id"),
                actor=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class BenefitTypeRuleViewSet(BaseBenefitViewSet):
    queryset = BenefitTypeRule.objects.select_related("benefit_type").all()
    serializer_class = BenefitTypeRuleSerializer
    filterset_fields = ["benefit_type"]
    search_fields = ["name", "benefit_type__name"]
    ordering = ["benefit_type__priority", "priority", "name"]


class EmployeeBenefitViewSet(BaseBenefitViewSet):
    queryset = EmployeeBenefit.objects.select_related(
        "employee", "employee__department", "employee__position", "benefit_type"
    ).all()
    serializer_class = EmployeeBenefitSerializer
    search_fields = ["employee__first_name", "employee__last_name", "employee__id_number", "benefit_type__name"]
    ordering_fields = ["priority", "created_at"]
    ordering = ["priority", "benefit_type__name"]

    def _require_finance_or_admin(self):
        require_manage_employee_benefit_assignments(self.request.user)

    def perform_create(self, serializer):
        self._require_finance_or_admin()
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._require_finance_or_admin()
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._require_finance_or_admin()
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"], url_path="revert-calculation")
    def revert_calculation(self, request, pk=None):
        self._require_finance_or_admin()
        assignment = self.get_object()
        try:
            assignment = revert_employee_benefit_calculation(assignment, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(EmployeeBenefitSerializer(assignment).data)

    def get_queryset(self):
        qs = super().get_queryset()
        employee_id = self.request.query_params.get("employee")
        benefit_type_id = self.request.query_params.get("benefit_type")
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        if benefit_type_id:
            qs = qs.filter(benefit_type_id=benefit_type_id)
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ("true", "1"))
        return qs


class BenefitRequestViewSet(BaseBenefitViewSet):
    queryset = BenefitRequest.objects.select_related(
        "benefit_type", "currency", "bank_account", "approved_by"
    ).annotate(line_count=Count("lines"))
    search_fields = ["request_number", "benefit_type__name"]
    ordering_fields = ["period_end", "payment_date", "created_at", "status"]
    ordering = ["-period_end", "-created_at"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return BenefitRequestDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return BenefitRequestWriteSerializer
        return BenefitRequestListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        benefit_type_id = self.request.query_params.get("benefit_type")
        if status_param:
            qs = qs.filter(status=status_param)
        if benefit_type_id:
            qs = qs.filter(benefit_type_id=benefit_type_id)
        return qs

    def retrieve(self, request, *args, **kwargs):
        instance = (
            BenefitRequest.objects.select_related(
                "benefit_type", "currency", "bank_account", "approved_by"
            )
            .prefetch_related(
                "lines__employee",
                "lines__employee__department",
                "lines__employee__position",
            )
            .get(pk=kwargs["pk"])
        )
        serializer = BenefitRequestDetailSerializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        benefit_request = self.get_object()
        serializer = GenerateBenefitRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            generate_benefit_request(
                benefit_request,
                employee_ids=serializer.validated_data.get("employee_ids"),
                actor=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        benefit_request.refresh_from_db()
        return Response(BenefitRequestDetailSerializer(benefit_request).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        benefit_request = self.get_object()
        try:
            submit_benefit_request_for_approval(benefit_request, user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BenefitRequestDetailSerializer(benefit_request).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        benefit_request = self.get_object()
        try:
            approve_benefit_request(benefit_request, user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BenefitRequestDetailSerializer(benefit_request).data)

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        benefit_request = self.get_object()
        try:
            mark_benefit_request_paid(benefit_request, user=request.user)
        except (ValueError, Exception) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BenefitRequestDetailSerializer(benefit_request).data)

    @action(detail=True, methods=["post"], url_path="revert-to-draft")
    def revert_to_draft(self, request, pk=None):
        benefit_request = self.get_object()
        try:
            revert_benefit_request_to_draft(benefit_request, user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BenefitRequestDetailSerializer(benefit_request).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        benefit_request = self.get_object()
        try:
            cancel_benefit_request(benefit_request, user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BenefitRequestDetailSerializer(benefit_request).data)


class BenefitRequestLineViewSet(BaseBenefitViewSet):
    queryset = BenefitRequestLine.objects.select_related(
        "request",
        "request__benefit_type",
        "employee",
        "employee__department",
        "employee__position",
    ).all()
    serializer_class = BenefitRequestLineSerializer
    search_fields = ["employee__first_name", "employee__last_name", "request__request_number"]
    ordering = ["-request__period_end", "employee__last_name"]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        qs = apply_employee_portal_benefit_filters(qs, self.request.user)
        employee_id = self.request.query_params.get("employee")
        request_id = self.request.query_params.get("request")
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        if request_id:
            qs = qs.filter(request_id=request_id)
        return qs

    def perform_update(self, serializer):
        instance = self.get_object()
        if instance.request.status == BenefitRequestStatus.PAID:
            from rest_framework.exceptions import ValidationError

            raise ValidationError("Paid benefit request lines cannot be modified.")
        instance = serializer.save(updated_by=self.request.user)
        instance.request.recalculate_totals()


class BenefitSettingsView(APIView):
    permission_classes = [EmployeeBenefitsAccessPolicy]

    def get(self, request):
        settings = get_tenant_benefit_settings()
        return Response(BenefitSettingsSerializer(settings).data)

    def patch(self, request):
        settings = get_tenant_benefit_settings()
        serializer = BenefitSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data)

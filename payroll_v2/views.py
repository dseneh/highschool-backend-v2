import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN

from django.db.models import Count, DecimalField, Prefetch, Q, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from hr.models import Employee
from academics.models import AcademicYear

from .enums import PayrollStatus, TargetAmountSource
from .access_policies import PayrollV2AccessPolicy
from .obligation_services import evaluate_employee_obligation_eligibility
from .models import (
    EmployeeCompensation,
    EmployeePayrollItem,
    EmployeeWard,
    PayrollCatalogItem,
    PayrollCatalogItemRule,
    PayrollDeductionInstallment,
    PayrollDeductionSchedule,
    PayrollEmployeeItem,
    PayrollPayslipTemplate,
    PayrollPeriod,
    PaySchedule,
    PayrollRunRecord,
    PayrollSettings,
    PayrollTableView,
    SalaryAdvance,
    StaffWardSponsorship,
    StaffWardSponsorshipPolicy,
    StaffWardSponsorshipStudent,
)
from .serializers import (
    DeductionInstallmentAdjustSerializer,
    DeductionInstallmentAutoAdjustSerializer,
    EmployeeCompensationSerializer,
    EmployeePayrollItemSerializer,
    EmployeeWardSerializer,
    GeneratePayrollSerializer,
    PayrollDeductionInstallmentSerializer,
    PayrollDeductionScheduleSerializer,
    PayrollEmployeeItemSerializer,
    PayrollItemRulePreviewSerializer,
    PayrollItemRuleSerializer,
    PayrollItemSerializer,
    PayrollPayslipTemplateSerializer,
    PayrollPeriodSerializer,
    PayScheduleSerializer,
    PayrollRunDetailSerializer,
    PayrollRunListSerializer,
    PayrollRunStatusActionSerializer,
    PayrollRunWriteSerializer,
    PayrollTableViewSerializer,
    PayrollSettingsSerializer,
    PayrollObligationEligibilityPreviewSerializer,
    WardSponsorshipWindowPreviewSerializer,
    SalaryAdvanceSerializer,
    SalaryAdvanceCancellationSerializer,
    SalaryAdvancePaymentRecordSerializer,
    SalaryAdvanceRepaymentRequestSerializer,
    StaffWardSponsorshipPolicySerializer,
    StaffWardSponsorshipSerializer,
    StaffWardSponsorshipStudentSerializer,
    WorkflowReasonSerializer,
)
from .services import (
    adjust_deduction_installment,
    auto_adjust_deduction_installment,
    approve_salary_advance,
    cancel_salary_advance,
    cancel_staff_ward_sponsorship,
    complete_salary_advance,
    complete_staff_ward_sponsorship,
    defer_deduction_installment,
    approve_staff_ward_sponsorship,
    approve_payroll,
    build_preview_item_rule_objects,
    ensure_salary_advance_can_be_deleted,
    ensure_staff_ward_sponsorship_can_be_deleted,
    generate_payroll,
    get_run_obligation_deduction_violations,
    get_payroll_v2_formula_guide,
    create_employee_compensation_record,
    update_employee_compensation_record,
    migrate_employee_salaries_to_compensation,
    mark_payroll_paid,
    preview_catalog_item_formula,
    preview_item_rules,
    request_salary_advance_early_repayment,
    reject_salary_advance,
    reject_staff_ward_sponsorship,
    remove_payroll_catalog_item_from_employees,
    revert_employee_payroll_item_calculation,
    revert_payroll_to_draft,
    submit_payroll_for_approval,
    submit_salary_advance_for_approval,
    submit_staff_ward_sponsorship_for_approval,
    sync_payroll_catalog_item_to_employees,
)
from .portal_access import apply_employee_portal_paystub_filters, employee_for_portal_user, user_can_manage_payroll_v2
from .schedule_services import derive_next_period
from .settings_services import (
    SALARY_ADVANCE_FEATURE,
    WARD_SPONSORSHIP_FEATURE,
    ensure_payroll_feature_enabled,
    get_tenant_payroll_settings,
)


TARGET_MIN_AMOUNT_OUTPUT_FIELD = DecimalField(max_digits=14, decimal_places=2)
TARGET_MIN_AMOUNT_SORT = Coalesce(
    "target_min_amount",
    Value(Decimal("0.00"), output_field=TARGET_MIN_AMOUNT_OUTPUT_FIELD),
    output_field=TARGET_MIN_AMOUNT_OUTPUT_FIELD,
)


def ordered_payroll_item_rules_queryset():
    return PayrollCatalogItemRule.objects.order_by(
        TARGET_MIN_AMOUNT_SORT,
        "priority",
        "name",
    )


class BasePayrollViewSet(viewsets.ModelViewSet):
    permission_classes = [PayrollV2AccessPolicy]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def require_payroll_feature(self, feature):
        try:
            ensure_payroll_feature_enabled(feature, user=self.request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return None


class EmployeeCompensationViewSet(BasePayrollViewSet):
    queryset = EmployeeCompensation.objects.select_related("employee", "currency").all()
    serializer_class = EmployeeCompensationSerializer
    search_fields = ["employee__first_name", "employee__last_name", "employee__id_number"]
    ordering_fields = ["effective_start_date", "base_amount", "created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        employee = self.request.query_params.get("employee")
        if employee:
            qs = qs.filter(employee_id=employee)
        is_active = self.request.query_params.get("is_active")
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=is_active == "true")
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        compensation = create_employee_compensation_record(
            employee=serializer.validated_data["employee"],
            pay_type=serializer.validated_data.get("pay_type"),
            base_amount=serializer.validated_data.get("base_amount"),
            hourly_rate=serializer.validated_data.get("hourly_rate"),
            daily_rate=serializer.validated_data.get("daily_rate"),
            currency=serializer.validated_data.get("currency"),
            effective_start_date=serializer.validated_data["effective_start_date"],
            effective_end_date=serializer.validated_data.get("effective_end_date"),
            notes=serializer.validated_data.get("notes", ""),
            actor=request.user,
        )
        output = self.get_serializer(compensation)
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)

    def partial_update(self, request, *args, **kwargs):
        compensation = self.get_object()
        serializer = self.get_serializer(compensation, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        compensation = update_employee_compensation_record(
            compensation,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(self.get_serializer(compensation).data)

    def update(self, request, *args, **kwargs):
        compensation = self.get_object()
        serializer = self.get_serializer(compensation, data=request.data)
        serializer.is_valid(raise_exception=True)
        compensation = update_employee_compensation_record(
            compensation,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(self.get_serializer(compensation).data)

    @action(detail=False, methods=["post"], url_path="migrate-from-employees")
    def migrate_from_employees(self, request):
        result = migrate_employee_salaries_to_compensation(actor=request.user)
        return Response(result, status=status.HTTP_200_OK)


class PayrollItemViewSet(BasePayrollViewSet):
    queryset = PayrollCatalogItem.objects.prefetch_related(
        Prefetch("rules", queryset=ordered_payroll_item_rules_queryset()),
    ).all()
    serializer_class = PayrollItemSerializer
    search_fields = ["name", "code", "description"]
    ordering_fields = ["priority", "name", "created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        line_type = self.request.query_params.get("line_type")
        is_active = self.request.query_params.get("is_active")
        if line_type:
            qs = qs.filter(line_type=line_type)
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=is_active == "true")
        return qs

    @action(detail=False, methods=["post"], url_path="preview-rules")
    def preview_rules(self, request):
        from decimal import Decimal

        rules_data = request.data.get("rules") or []
        serializer = PayrollItemRulePreviewSerializer(data=rules_data, many=True)
        serializer.is_valid(raise_exception=True)
        rules = build_preview_item_rule_objects(serializer.validated_data)
        try:
            basic = Decimal(str(request.data.get("basic", request.data.get("gross", "0"))))
            gross = Decimal(str(request.data.get("gross", basic)))
            taxable = request.data.get("taxable_income")
            annual = request.data.get("annual")
            annual_salary = Decimal(str(annual)) if annual is not None else None
            taxable_income = Decimal(str(taxable)) if taxable is not None else None
        except (TypeError, ValueError):
            return Response({"detail": "Invalid numeric input."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = preview_item_rules(
                rules=rules,
                basic_salary=basic,
                gross_pay=gross,
                taxable_income=taxable_income,
                annual_salary=annual_salary,
                periods_per_year=request.data.get("periods_per_year"),
            )
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    @action(detail=False, methods=["get"], url_path="formula-guide")
    def formula_guide(self, request):
        return Response(get_payroll_v2_formula_guide())

    @action(detail=False, methods=["post"], url_path="preview-formula")
    def preview_formula(self, request):
        from decimal import Decimal

        try:
            basic = Decimal(str(request.data.get("basic", request.data.get("gross", "1000"))))
            gross = Decimal(str(request.data.get("gross", basic)))
            allowances = Decimal(str(request.data.get("allowances", "0")))
            deductions = Decimal(str(request.data.get("deductions", "0")))
            taxable_income = request.data.get("taxable_income")
            annual = request.data.get("annual")
        except (TypeError, ValueError):
            return Response({"detail": "Invalid numeric input."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = preview_catalog_item_formula(
                calculation_type=request.data.get("calculation_type", "formula"),
                value=request.data.get("value", "0"),
                formula=str(request.data.get("formula", "") or ""),
                target_amount_source=request.data.get(
                    "target_amount_source",
                    TargetAmountSource.BASIC_SALARY,
                ),
                gross=gross,
                basic=basic,
                allowances=allowances,
                deductions=deductions,
                target_min_amount=request.data.get("target_min_amount"),
                target_max_amount=request.data.get("target_max_amount"),
                calculation_limit=request.data.get("calculation_limit"),
                periods_per_year=request.data.get("periods_per_year"),
                annual_salary=Decimal(str(annual)) if annual is not None else None,
                taxable_income=Decimal(str(taxable_income)) if taxable_income is not None else None,
            )
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    @action(detail=True, methods=["post"], url_path="sync-employees")
    def sync_employees(self, request, pk=None):
        payroll_item = self.get_object()
        scope = str(request.data.get("scope", "all"))
        employee_ids = request.data.get("employee_ids") or []
        employee_identifiers = request.data.get("employee_identifiers") or []
        department_id = request.data.get("department_id")
        position_id = request.data.get("position_id")

        combined_identifiers = list(employee_ids) + list(employee_identifiers)
        try:
            result = sync_payroll_catalog_item_to_employees(
                payroll_item=payroll_item,
                scope=scope,
                employee_ids=combined_identifiers if scope.strip().lower() == "selected" else None,
                department_id=department_id,
                position_id=position_id,
                actor=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        created = result["created"]
        reactivated = result["reactivated"]
        already_assigned = result["already_assigned"]
        detail = f"Assigned '{result['payroll_item_name']}' to {created + reactivated} employee(s)."
        if already_assigned:
            detail += f" {already_assigned} already had this item."
        if reactivated:
            detail += f" {reactivated} inactive assignment(s) were reactivated."

        return Response(
            {
                "detail": detail,
                "targeted": result["targeted"],
                "created": created,
                "reactivated": reactivated,
                "already_assigned": already_assigned,
                "payroll_item_id": result["payroll_item_id"],
                "scope": result["scope"],
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="remove-from-employees")
    def remove_from_employees(self, request, pk=None):
        payroll_item = self.get_object()
        scope = str(request.data.get("scope", "all"))
        employee_ids = request.data.get("employee_ids") or []
        employee_identifiers = request.data.get("employee_identifiers") or []
        department_id = request.data.get("department_id")
        position_id = request.data.get("position_id")

        combined_identifiers = list(employee_ids) + list(employee_identifiers)
        try:
            result = remove_payroll_catalog_item_from_employees(
                payroll_item=payroll_item,
                scope=scope,
                employee_ids=combined_identifiers if scope.strip().lower() == "selected" else None,
                department_id=department_id,
                position_id=position_id,
                actor=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        removed = result["removed"]
        deactivated = result["deactivated"]
        detail = f"Removed '{result['payroll_item_name']}' from {removed} employee assignment(s)."
        if deactivated:
            detail += (
                f" Deactivated {deactivated} assignment(s) that already appear on generated payroll runs."
            )

        return Response(
            {
                "detail": detail,
                "targeted": result["targeted"],
                "removed": removed,
                "deactivated": deactivated,
                "payroll_item_id": result["payroll_item_id"],
                "scope": result["scope"],
            },
            status=status.HTTP_200_OK,
        )


class PayrollItemRuleViewSet(BasePayrollViewSet):
    queryset = (
        PayrollCatalogItemRule.objects.select_related("payroll_item")
        .annotate(_min_sort=TARGET_MIN_AMOUNT_SORT)
        .order_by("_min_sort", "priority", "name")
    )
    serializer_class = PayrollItemRuleSerializer
    search_fields = ["name", "payroll_item__name", "payroll_item__code", "notes"]
    ordering_fields = ["priority", "target_min_amount", "target_max_amount", "created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        payroll_item = self.request.query_params.get("payroll_item")
        if payroll_item:
            qs = qs.filter(payroll_item_id=payroll_item)
        return qs


class EmployeePayrollItemViewSet(BasePayrollViewSet):
    queryset = (
        EmployeePayrollItem.objects.select_related("employee", "payroll_item")
        .prefetch_related(Prefetch("payroll_item__rules", queryset=ordered_payroll_item_rules_queryset()))
        .all()
    )
    serializer_class = EmployeePayrollItemSerializer
    search_fields = [
        "employee__first_name",
        "employee__last_name",
        "employee__id_number",
        "payroll_item__name",
        "payroll_item__code",
    ]
    ordering_fields = ["priority", "start_date", "end_date", "created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        employee = self.request.query_params.get("employee")
        if employee:
            qs = qs.filter(employee_id=employee)
        return qs

    @action(detail=True, methods=["post"], url_path="revert-calculation")
    def revert_calculation(self, request, pk=None):
        assignment = self.get_object()
        try:
            assignment = revert_employee_payroll_item_calculation(assignment, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(EmployeePayrollItemSerializer(assignment, context=self.get_serializer_context()).data)


class PayScheduleViewSet(BasePayrollViewSet):
    queryset = PaySchedule.objects.select_related("currency").all()
    serializer_class = PayScheduleSerializer
    search_fields = ["name"]
    ordering_fields = ["name", "created_at", "is_default"]

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    @action(detail=True, methods=["get"], url_path="next-period")
    def next_period(self, request, pk=None):
        schedule = self.get_object()
        derived = derive_next_period(schedule)
        return Response(
            {
                "name": derived.name,
                "start_date": derived.start_date,
                "end_date": derived.end_date,
                "payment_date": derived.payment_date,
            }
        )

    @action(detail=True, methods=["post"], url_path="sync-employees")
    def sync_employees(self, request, pk=None):
        schedule = self.get_object()
        only_without_schedule = bool(request.data.get("only_without_schedule", False))

        qs = Employee.objects.all()
        if only_without_schedule:
            qs = qs.filter(pay_schedule__isnull=True)

        updated = qs.update(pay_schedule=schedule, updated_by=request.user)

        return Response(
            {
                "detail": f"Assigned schedule '{schedule.name}' to {updated} employee(s).",
                "updated": updated,
                "schedule_id": str(schedule.id),
                "only_without_schedule": only_without_schedule,
            },
            status=status.HTTP_200_OK,
        )


class PayrollPeriodViewSet(BasePayrollViewSet):
    queryset = PayrollPeriod.objects.select_related("schedule", "schedule__currency").all()
    serializer_class = PayrollPeriodSerializer
    search_fields = ["name"]
    ordering_fields = ["start_date", "end_date", "payment_date"]

    def get_queryset(self):
        qs = super().get_queryset()
        schedule = self.request.query_params.get("schedule")
        if schedule:
            qs = qs.filter(schedule_id=schedule)
        return qs


class StaffWardSponsorshipPolicyViewSet(BasePayrollViewSet):
    queryset = StaffWardSponsorshipPolicy.objects.all()
    serializer_class = StaffWardSponsorshipPolicySerializer
    search_fields = ["name", "description"]
    ordering_fields = ["effective_from", "created_at", "name"]

    def create(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().partial_update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        is_active = self.request.query_params.get("is_active")
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=is_active == "true")
        return qs


class EmployeeWardViewSet(BasePayrollViewSet):
    queryset = EmployeeWard.objects.select_related("employee", "student", "verified_by")
    serializer_class = EmployeeWardSerializer
    search_fields = ["employee__first_name", "employee__last_name", "employee__id_number", "student__id_number"]
    ordering_fields = ["created_at", "verification_date"]

    def create(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().partial_update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        employee = self.request.query_params.get("employee")
        student = self.request.query_params.get("student")
        is_active = self.request.query_params.get("is_active")
        if employee:
            qs = qs.filter(employee_id=employee)
        if student:
            qs = qs.filter(student_id=student)
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=is_active == "true")
        return qs


class StaffWardSponsorshipViewSet(BasePayrollViewSet):
    queryset = StaffWardSponsorship.objects.select_related("employee", "policy", "academic_year")
    serializer_class = StaffWardSponsorshipSerializer
    search_fields = ["employee__first_name", "employee__last_name", "employee__id_number"]
    ordering_fields = ["application_date", "created_at", "status"]

    def create(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().partial_update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().update(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        employee = self.request.query_params.get("employee")
        status_filter = self.request.query_params.get("status")
        academic_year = self.request.query_params.get("academic_year")
        if employee:
            qs = qs.filter(employee_id=employee)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        return qs

    def destroy(self, request, *args, **kwargs):
        sponsorship = self.get_object()
        is_manager = user_can_manage_payroll_v2(request.user)
        if not is_manager:
            employee = employee_for_portal_user(request.user)
            if employee is None or employee.id != sponsorship.employee_id:
                return Response(
                    {"detail": "You can only delete your own ward sponsorship requests."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        try:
            ensure_staff_ward_sponsorship_can_be_deleted(sponsorship, self_service=not is_manager)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        try:
            sponsorship = submit_staff_ward_sponsorship_for_approval(self.get_object(), request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(sponsorship).data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        try:
            sponsorship = approve_staff_ward_sponsorship(self.get_object(), request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(sponsorship).data)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        try:
            sponsorship = complete_staff_ward_sponsorship(self.get_object(), request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(sponsorship).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        serializer = WorkflowReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            sponsorship = reject_staff_ward_sponsorship(
                self.get_object(),
                reason=serializer.validated_data.get("reason", ""),
                user=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(sponsorship).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        serializer = WorkflowReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            sponsorship = cancel_staff_ward_sponsorship(
                self.get_object(),
                reason=serializer.validated_data.get("reason", ""),
                user=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(sponsorship).data)


class StaffWardSponsorshipStudentViewSet(BasePayrollViewSet):
    queryset = StaffWardSponsorshipStudent.objects.select_related("sponsorship", "employee_ward", "student", "enrollment")
    serializer_class = StaffWardSponsorshipStudentSerializer
    search_fields = ["student__first_name", "student__last_name", "student__id_number"]
    ordering_fields = ["created_at", "eligible_fee_total", "employee_responsibility_amount"]

    def create(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().partial_update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(WARD_SPONSORSHIP_FEATURE):
            return response
        return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        sponsorship = self.request.query_params.get("sponsorship")
        if sponsorship:
            qs = qs.filter(sponsorship_id=sponsorship)
        return qs


class SalaryAdvanceViewSet(BasePayrollViewSet):
    queryset = SalaryAdvance.objects.select_related("employee", "approved_by", "repayment_start_period")
    serializer_class = SalaryAdvanceSerializer
    search_fields = ["employee__first_name", "employee__last_name", "employee__id_number", "notes"]
    ordering_fields = ["request_date", "created_at", "status", "remaining_balance"]

    def create(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(SALARY_ADVANCE_FEATURE):
            return response
        return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(SALARY_ADVANCE_FEATURE):
            return response
        return super().partial_update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if response := self.require_payroll_feature(SALARY_ADVANCE_FEATURE):
            return response
        return super().update(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        employee = self.request.query_params.get("employee")
        status_filter = self.request.query_params.get("status")
        if employee:
            qs = qs.filter(employee_id=employee)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def destroy(self, request, *args, **kwargs):
        advance = self.get_object()
        is_manager = user_can_manage_payroll_v2(request.user)
        if not is_manager:
            employee = employee_for_portal_user(request.user)
            if employee is None or employee.id != advance.employee_id:
                return Response(
                    {"detail": "You can only delete your own salary advance requests."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        try:
            ensure_salary_advance_can_be_deleted(advance, self_service=not is_manager)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        if response := self.require_payroll_feature(SALARY_ADVANCE_FEATURE):
            return response
        try:
            advance = submit_salary_advance_for_approval(self.get_object(), request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(advance).data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        if response := self.require_payroll_feature(SALARY_ADVANCE_FEATURE):
            return response
        try:
            advance = approve_salary_advance(self.get_object(), request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(advance).data)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        if response := self.require_payroll_feature(SALARY_ADVANCE_FEATURE):
            return response
        try:
            advance = complete_salary_advance(self.get_object(), request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(advance).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        if response := self.require_payroll_feature(SALARY_ADVANCE_FEATURE):
            return response
        serializer = SalaryAdvanceCancellationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            advance = cancel_salary_advance(
                self.get_object(),
                reason=serializer.validated_data["reason"],
                user=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(advance).data)

    @action(detail=True, methods=["post"], url_path="record-payment")
    def record_payment(self, request, pk=None):
        if response := self.require_payroll_feature(SALARY_ADVANCE_FEATURE):
            return response
        from authorization.runtime import user_has_permission

        if not user_has_permission(request.user, "payroll.process"):
            return Response({"detail": "Only finance users can request early repayments."}, status=status.HTTP_403_FORBIDDEN)

        serializer = SalaryAdvancePaymentRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = request_salary_advance_early_repayment(
                self.get_object(),
                amount=serializer.validated_data["amount"],
                payment_date=serializer.validated_data.get("payment_date"),
                payment_method=serializer.validated_data.get("payment_method"),
                reference=serializer.validated_data.get("reference", ""),
                notes=serializer.validated_data.get("notes", ""),
                user=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SalaryAdvanceRepaymentRequestSerializer(payload).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        if response := self.require_payroll_feature(SALARY_ADVANCE_FEATURE):
            return response
        serializer = WorkflowReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            advance = reject_salary_advance(
                self.get_object(),
                reason=serializer.validated_data.get("reason", ""),
                user=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(advance).data)


class PayrollDeductionScheduleViewSet(BasePayrollViewSet):
    queryset = PayrollDeductionSchedule.objects.select_related("employee", "start_period", "end_period")
    serializer_class = PayrollDeductionScheduleSerializer
    search_fields = ["employee__first_name", "employee__last_name", "employee__id_number", "source_id"]
    ordering_fields = ["created_at", "remaining_amount", "status"]

    def get_queryset(self):
        qs = super().get_queryset()
        employee = self.request.query_params.get("employee")
        source_type = self.request.query_params.get("source_type")
        status_filter = self.request.query_params.get("status")
        if employee:
            qs = qs.filter(employee_id=employee)
        if source_type:
            qs = qs.filter(source_type=source_type)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class PayrollDeductionInstallmentViewSet(BasePayrollViewSet):
    queryset = PayrollDeductionInstallment.objects.select_related(
        "deduction_schedule",
        "deduction_schedule__employee",
        "payroll_period",
        "payroll_line",
    )
    serializer_class = PayrollDeductionInstallmentSerializer
    search_fields = ["deduction_schedule__employee__first_name", "deduction_schedule__employee__last_name"]
    ordering_fields = ["created_at", "scheduled_amount", "actual_amount", "status"]

    def get_queryset(self):
        qs = super().get_queryset()
        deduction_schedule = self.request.query_params.get("deduction_schedule")
        payroll_period = self.request.query_params.get("payroll_period")
        status_filter = self.request.query_params.get("status")
        if deduction_schedule:
            qs = qs.filter(deduction_schedule_id=deduction_schedule)
        if payroll_period:
            qs = qs.filter(payroll_period_id=payroll_period)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=["post"], url_path="adjust")
    def adjust(self, request, pk=None):
        serializer = DeductionInstallmentAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            installment = adjust_deduction_installment(
                installment=self.get_object(),
                amount=serializer.validated_data["amount"],
                reason=serializer.validated_data.get("reason", ""),
                actor=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(installment).data)

    @action(detail=True, methods=["post"], url_path="defer")
    def defer(self, request, pk=None):
        serializer = WorkflowReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        installment = defer_deduction_installment(
            installment=self.get_object(),
            reason=serializer.validated_data.get("reason", ""),
            actor=request.user,
        )
        return Response(self.get_serializer(installment).data)

    @action(detail=True, methods=["post"], url_path="auto-adjust")
    def auto_adjust(self, request, pk=None):
        serializer = DeductionInstallmentAutoAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        installment = auto_adjust_deduction_installment(
            installment=self.get_object(),
            max_allowed_amount=serializer.validated_data["max_allowed_amount"],
            reason=serializer.validated_data.get("reason", ""),
            actor=request.user,
        )
        return Response(self.get_serializer(installment).data)


class PayrollRunViewSet(BasePayrollViewSet):
    queryset = (
        PayrollRunRecord.objects.annotate(employee_count=Count("employee_items"))
        .select_related(
            "currency",
            "bank_account",
            "table_view",
            "payslip_template",
            "pay_schedule",
            "payroll_period",
        )
        .order_by("-pay_period_end", "-created_at")
    )
    search_fields = ["payroll_number", "notes"]
    ordering = ["-pay_period_end", "-created_at"]
    ordering_fields = ["pay_period_start", "pay_period_end", "payment_date", "created_at", "status"]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        pay_schedule = self.request.query_params.get("pay_schedule")
        if pay_schedule:
            qs = qs.filter(pay_schedule_id=pay_schedule)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(payroll_number__icontains=search) | Q(notes__icontains=search))
        return qs

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return PayrollRunWriteSerializer
        if self.action == "retrieve":
            return PayrollRunDetailSerializer
        return PayrollRunListSerializer

    @action(detail=True, methods=["post"], url_path="generate")
    def generate(self, request, pk=None):
        payroll_run = self.get_object()
        serializer = GeneratePayrollSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        employee_ids = serializer.validated_data.get("employee_ids") or []
        if employee_ids:
            employees = Employee.objects.filter(id__in=employee_ids)
        else:
            employees = Employee.objects.filter(employment_status=Employee.EmploymentStatus.ACTIVE)
            if payroll_run.pay_schedule_id:
                employees = employees.filter(pay_schedule_id=payroll_run.pay_schedule_id)

        table_view = None
        table_view_id = serializer.validated_data.get("table_view_id")
        if table_view_id:
            table_view = PayrollTableView.objects.filter(id=table_view_id, active=True).first()

        try:
            payroll_run = generate_payroll(
                payroll_run,
                employees=employees,
                generated_by=request.user,
                replace_existing=serializer.validated_data["replace_existing"],
                table_view=table_view,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        data = PayrollRunDetailSerializer(payroll_run, context=self.get_serializer_context()).data
        generation_meta = getattr(payroll_run, "generation_meta", None)
        if generation_meta:
            data["generation_meta"] = generation_meta
        return Response(data)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        payroll_run = self.get_object()
        serializer = PayrollRunStatusActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("note"):
            payroll_run.notes = (payroll_run.notes + "\n" if payroll_run.notes else "") + serializer.validated_data["note"]
            payroll_run.save(update_fields=["notes", "updated_at"])
        try:
            payroll_run = submit_payroll_for_approval(payroll_run, request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PayrollRunDetailSerializer(payroll_run, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["get"], url_path="obligation-violations")
    def obligation_violations(self, request, pk=None):
        payload = get_run_obligation_deduction_violations(self.get_object())
        return Response(payload)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        try:
            payroll_run = approve_payroll(self.get_object(), request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PayrollRunDetailSerializer(payroll_run, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        try:
            payroll_run = mark_payroll_paid(self.get_object(), request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PayrollRunDetailSerializer(payroll_run, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="revert-to-draft")
    def revert_to_draft(self, request, pk=None):
        try:
            payroll_run = revert_payroll_to_draft(self.get_object(), request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PayrollRunDetailSerializer(payroll_run, context=self.get_serializer_context()).data)


class PayrollEmployeeItemViewSet(BasePayrollViewSet):
    queryset = PayrollEmployeeItem.objects.select_related(
        "payroll",
        "payroll__pay_schedule",
        "employee",
        "employee__department",
        "employee__position",
    ).prefetch_related("line_items")
    serializer_class = PayrollEmployeeItemSerializer
    search_fields = [
        "employee__first_name",
        "employee__last_name",
        "employee__id_number",
        "payroll__payroll_number",
    ]
    ordering_fields = ["created_at", "gross_pay", "net_pay", "payment_status"]

    def get_queryset(self):
        qs = super().get_queryset()
        payroll = self.request.query_params.get("payroll")
        employee = self.request.query_params.get("employee")
        if payroll:
            qs = qs.filter(payroll_id=payroll)
        if employee:
            qs = qs.filter(employee_id=employee)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
                | Q(employee__id_number__icontains=search)
            )
        return apply_employee_portal_paystub_filters(qs, self.request.user)

    def _reject_if_paid_run(self, item):
        if item.payroll.status == PayrollStatus.PAID:
            from rest_framework.exceptions import ValidationError

            raise ValidationError("Paid payroll run items cannot be modified.")

    def partial_update(self, request, *args, **kwargs):
        self._reject_if_paid_run(self.get_object())
        return super().partial_update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        self._reject_if_paid_run(self.get_object())
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="recalculate")
    def recalculate(self, request, pk=None):
        item = self.get_object()
        self._reject_if_paid_run(item)
        item.recalculate_totals()
        item.payroll.recalculate_totals()
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        import logging

        from common.services.pdf_components import resolve_tenant_school

        from .paystub_pdf import build_paystub_v2_pdf_bytes

        logger = logging.getLogger(__name__)
        item = self.get_object()
        try:
            pdf_bytes = build_paystub_v2_pdf_bytes(item, school=resolve_tenant_school())
        except Exception as exc:
            logger.exception("Paystub PDF generation failed for employee run item %s", item.id)
            return Response(
                {"detail": f"Could not generate paystub PDF: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        employee_name = item.employee.get_full_name().strip()
        period_label = f"{item.payroll.pay_period_start:%Y-%m-%d}_{item.payroll.pay_period_end:%Y-%m-%d}"
        safe_employee = (employee_name or item.employee.id_number or str(item.employee_id)).replace(" ", "_")
        filename = f"paystub_{safe_employee}_{period_label}.pdf"

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class PayrollTableViewViewSet(BasePayrollViewSet):
    queryset = PayrollTableView.objects.all()
    serializer_class = PayrollTableViewSerializer
    search_fields = ["name", "description", "applies_to"]
    ordering_fields = ["name", "is_default", "created_at"]

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        if instance.is_default:
            PayrollTableView.objects.exclude(id=instance.id).filter(applies_to=instance.applies_to).update(
                is_default=False
            )

    def perform_update(self, serializer):
        instance = serializer.save(updated_by=self.request.user)
        if instance.is_default:
            PayrollTableView.objects.exclude(id=instance.id).filter(applies_to=instance.applies_to).update(
                is_default=False
            )


class PayrollPayslipTemplateViewSet(BasePayrollViewSet):
    queryset = PayrollPayslipTemplate.objects.all()
    serializer_class = PayrollPayslipTemplateSerializer
    search_fields = ["name", "description"]
    ordering_fields = ["name", "is_default", "created_at"]

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        if instance.is_default:
            PayrollPayslipTemplate.objects.exclude(id=instance.id).update(is_default=False)

    def perform_update(self, serializer):
        instance = serializer.save(updated_by=self.request.user)
        if instance.is_default:
            PayrollPayslipTemplate.objects.exclude(id=instance.id).update(is_default=False)


class PayrollSchoolHeaderView(APIView):
    """Employer / school block for payslips and payroll exports."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .school_header import build_payroll_school_header

        payload = build_payroll_school_header(request)
        if not payload:
            return Response(
                {"detail": "School not found for this workspace."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(payload)


class PayrollSettingsView(APIView):
    """Tenant payroll accounting and paystub configuration."""

    permission_classes = [PayrollV2AccessPolicy]

    def get(self, request):
        settings = get_tenant_payroll_settings(user=request.user)
        return Response(PayrollSettingsSerializer(settings).data)

    def patch(self, request):
        settings = get_tenant_payroll_settings(user=request.user)
        serializer = PayrollSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        settings = serializer.save(updated_by=request.user)
        settings.refresh_from_db()
        return Response(PayrollSettingsSerializer(settings).data)


class PayrollObligationEligibilityPreviewView(APIView):
    """Preview shared salary advance and ward sponsorship eligibility calculations."""

    permission_classes = [PayrollV2AccessPolicy]

    def post(self, request):
        serializer = PayrollObligationEligibilityPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        feature = (
            SALARY_ADVANCE_FEATURE
            if serializer.validated_data["obligation_type"] == "salary_advance"
            else WARD_SPONSORSHIP_FEATURE
        )
        try:
            ensure_payroll_feature_enabled(feature, user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        employee_id = serializer.validated_data["employee"]
        employee = Employee.objects.filter(id=employee_id).first()
        if employee is None:
            return Response({"detail": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)

        settings = get_tenant_payroll_settings(user=request.user)
        payload = evaluate_employee_obligation_eligibility(
            employee=employee,
            payroll_settings=settings,
            obligation_type=serializer.validated_data["obligation_type"],
            requested_periodic_deduction=serializer.validated_data.get("requested_periodic_deduction"),
            requested_amount=serializer.validated_data.get("requested_amount"),
            requested_installments=serializer.validated_data.get("requested_installments"),
            repayment_method=serializer.validated_data.get("repayment_method"),
            fixed_installment_amount=serializer.validated_data.get("fixed_installment_amount"),
            exclude_source_type=serializer.validated_data["obligation_type"],
            exclude_source_id=serializer.validated_data.get("exclude_source_id") or None,
        )
        return Response(payload)


class WardSponsorshipWindowPreviewView(APIView):
    """Preview sponsorship application window and repayment periods using backend rules."""

    permission_classes = [PayrollV2AccessPolicy]

    @staticmethod
    def _add_months(base_date: date, months: int) -> date:
        total_month_index = (base_date.year * 12 + (base_date.month - 1)) + max(0, int(months))
        year = total_month_index // 12
        month = (total_month_index % 12) + 1
        max_day = calendar.monthrange(year, month)[1]
        day = min(base_date.day, max_day)
        return date(year, month, day)

    @classmethod
    def _month_index(cls, *, year_start: date, target: date) -> int:
        return ((target.year - year_start.year) * 12) + (target.month - year_start.month) + 1

    @staticmethod
    def _month_starts_between(start_date: date, end_date: date):
        if start_date > end_date:
            return []
        cursor = date(start_date.year, start_date.month, 1)
        last = date(end_date.year, end_date.month, 1)
        months = []
        while cursor <= last:
            months.append(cursor)
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)
        return months

    @classmethod
    def _build_repayment_schedule_preview(cls, *, total_amount: Decimal, start_date: date, end_date: date):
        total = Decimal(str(total_amount or "0"))
        if total <= Decimal("0"):
            return {
                "months_remaining": 0,
                "monthly_deduction": "0.00",
                "schedule": [],
            }

        months = cls._month_starts_between(start_date=start_date, end_date=end_date)
        if not months:
            return {
                "months_remaining": 0,
                "monthly_deduction": "0.00",
                "schedule": [],
            }

        count = len(months)
        base = total if count == 1 else (total / Decimal(str(count))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        remaining = total.quantize(Decimal("0.01"))
        rows = []

        for idx, month_start in enumerate(months, start=1):
            deduction = remaining if idx == count else min(base, remaining)
            remaining = (remaining - deduction).quantize(Decimal("0.01"))

            max_day = calendar.monthrange(month_start.year, month_start.month)[1]
            payment_day = min(start_date.day, max_day)
            repayment_date = date(month_start.year, month_start.month, payment_day)

            rows.append(
                {
                    "installment_number": idx,
                    "month_label": month_start.strftime("%B %Y"),
                    "repayment_date": repayment_date.isoformat(),
                    "deduction_amount": f"{deduction.quantize(Decimal('0.01'))}",
                    "remaining_balance": f"{remaining}",
                }
            )

        return {
            "months_remaining": count,
            "monthly_deduction": f"{base.quantize(Decimal('0.01'))}",
            "schedule": rows,
        }

    def post(self, request):
        try:
            ensure_payroll_feature_enabled(WARD_SPONSORSHIP_FEATURE, user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = WardSponsorshipWindowPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        academic_year = AcademicYear.objects.filter(id=serializer.validated_data["academic_year"]).first()
        if academic_year is None:
            return Response({"detail": "Academic year not found."}, status=status.HTTP_404_NOT_FOUND)
        if not academic_year.start_date or not academic_year.end_date:
            return Response(
                {"detail": "Selected academic year must have valid start and end dates."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        settings = get_tenant_payroll_settings(user=request.user)
        deadline_months = max(1, int(getattr(settings, "ward_sponsorship_application_deadline_months", 3) or 3))

        today = date.today()
        within_year = academic_year.start_date <= today <= academic_year.end_date
        total_months = max(1, self._month_index(year_start=academic_year.start_date, target=academic_year.end_date))
        current_month_index = self._month_index(year_start=academic_year.start_date, target=today) if within_year else None

        start_period_id = (serializer.validated_data.get("start_period") or "").strip()
        start_period = PayrollPeriod.objects.filter(id=start_period_id).first() if start_period_id else None
        repayment_reference_date = start_period.start_date if start_period is not None else today
        if repayment_reference_date < academic_year.start_date:
            repayment_reference_date = academic_year.start_date

        repayment_month_index = (
            self._month_index(year_start=academic_year.start_date, target=repayment_reference_date)
            if repayment_reference_date <= academic_year.end_date
            else None
        )
        months_remaining = (
            max(0, total_months - repayment_month_index + 1)
            if repayment_month_index is not None
            else 0
        )

        deadline_end = self._add_months(academic_year.start_date, deadline_months) - timedelta(days=1)
        is_open = within_year and today <= deadline_end

        repayment_periods = []
        expected_end_period = None

        if start_period is not None:
            repayment_periods = list(
                PayrollPeriod.objects.filter(
                    schedule_id=start_period.schedule_id,
                    start_date__gte=start_period.start_date,
                    start_date__lte=academic_year.end_date,
                    is_closed=False,
                ).order_by("start_date")
            )
            if repayment_periods:
                expected_end_period = repayment_periods[-1]

        total_sponsorship_amount = Decimal(str(serializer.validated_data.get("total_sponsorship_amount") or "0"))
        repayment_schedule_preview = self._build_repayment_schedule_preview(
            total_amount=total_sponsorship_amount,
            start_date=repayment_reference_date,
            end_date=academic_year.end_date,
        )

        payload = {
            "academic_year": str(academic_year.id),
            "academic_year_name": academic_year.name,
            "academic_year_start_date": academic_year.start_date.isoformat(),
            "academic_year_end_date": academic_year.end_date.isoformat(),
            "deadline_months": deadline_months,
            "deadline_end_date": deadline_end.isoformat(),
            "current_date": today.isoformat(),
            "current_month_index": current_month_index,
            "repayment_month_index": repayment_month_index,
            "total_months_in_academic_year": total_months,
            "months_remaining_in_academic_year": months_remaining,
            "repayment_reference_date": repayment_reference_date.isoformat(),
            "is_within_academic_year": within_year,
            "is_within_deadline": today <= deadline_end if within_year else False,
            "is_application_window_open": is_open,
            "total_sponsorship_amount": f"{total_sponsorship_amount.quantize(Decimal('0.01'))}",
            "monthly_deduction_amount": repayment_schedule_preview["monthly_deduction"],
            "repayment_schedule_preview": repayment_schedule_preview["schedule"],
            "eligible_repayment_periods": [
                {
                    "id": str(period.id),
                    "name": period.name,
                    "start_date": period.start_date.isoformat(),
                    "end_date": period.end_date.isoformat(),
                    "payment_date": period.payment_date.isoformat(),
                }
                for period in repayment_periods
            ],
            "expected_end_period": {
                "id": str(expected_end_period.id),
                "name": expected_end_period.name,
                "start_date": expected_end_period.start_date.isoformat(),
                "end_date": expected_end_period.end_date.isoformat(),
                "payment_date": expected_end_period.payment_date.isoformat(),
            }
            if expected_end_period
            else None,
        }
        return Response(payload)

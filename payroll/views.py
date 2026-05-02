"""Payroll viewsets."""

from __future__ import annotations

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .access_policies import PayrollAccessPolicy
from .models import (
    PayrollItem,
    PayrollItemType,
    PayrollPeriod,
    PayrollRun,
    Payslip,
    PaySchedule,
    TaxRule,
    EmployeeTaxRuleOverride,
)
from .serializers import (
    PayrollItemSerializer,
    PayrollItemTypeSerializer,
    PayrollPeriodSerializer,
    PayrollRunSerializer,
    PayScheduleSerializer,
    PayslipSerializer,
    TaxRuleSerializer,
    EmployeeTaxRuleOverrideSerializer,
)
from .services import (
    apply_tax_rules,
    approve_run,
    derive_next_period,
    generate_payslips,
    mark_paid as mark_paid_service,
    recalculate_payslip,
    revert_to_draft as revert_to_draft_service,
    submit_for_approval,
)


class _BaseAuditedViewSet(viewsets.ModelViewSet):
    permission_classes = [PayrollAccessPolicy]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class PayScheduleViewSet(_BaseAuditedViewSet):
    queryset = PaySchedule.objects.select_related("currency").all()
    serializer_class = PayScheduleSerializer

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


class PayrollPeriodViewSet(_BaseAuditedViewSet):
    queryset = PayrollPeriod.objects.select_related("schedule", "schedule__currency").all()
    serializer_class = PayrollPeriodSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        schedule_id = self.request.query_params.get("schedule")
        if schedule_id:
            qs = qs.filter(schedule_id=schedule_id)
        return qs


class PayrollRunViewSet(_BaseAuditedViewSet):
    queryset = (
        PayrollRun.objects.select_related(
            "period", "period__schedule", "period__schedule__currency"
        )
        .prefetch_related("payslips")
        .all()
    )
    serializer_class = PayrollRunSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        schedule_id = self.request.query_params.get("schedule")
        if schedule_id:
            qs = qs.filter(period__schedule_id=schedule_id)
        return qs

    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        run = self.get_object()
        try:
            payslips = generate_payslips(run, regenerate=False)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"detail": f"Generated {len(payslips)} payslips.", "count": len(payslips)},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        run = self.get_object()
        try:
            payslips = generate_payslips(run, regenerate=True)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"detail": f"Regenerated {len(payslips)} payslips.", "count": len(payslips)},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        run = self.get_object()
        try:
            run = submit_for_approval(run)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(run).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        run = self.get_object()
        try:
            run = approve_run(run)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(run).data)

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        run = self.get_object()
        try:
            run = mark_paid_service(run)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(run).data)

    @action(detail=True, methods=["post"], url_path="revert-to-draft")
    def revert_to_draft(self, request, pk=None):
        run = self.get_object()
        try:
            run = revert_to_draft_service(run)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(run).data)


class PayslipViewSet(_BaseAuditedViewSet):
    queryset = Payslip.objects.select_related(
        "payroll_run", "employee", "currency"
    ).all()
    serializer_class = PayslipSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        run_id = self.request.query_params.get("payroll_run")
        if run_id:
            qs = qs.filter(payroll_run_id=run_id)
        employee_id = self.request.query_params.get("employee")
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
                | Q(employee__employee_number__icontains=search)
            )
        return qs

    def update(self, request, *args, **kwargs):
        # Only allow updating overtime_hours and unpaid_leave_days on DRAFT runs.
        instance = self.get_object()
        if instance.payroll_run.status != PayrollRun.Status.DRAFT:
            return Response(
                {"detail": "Payslips can only be edited while the run is in DRAFT."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        editable = {"overtime_hours", "unpaid_leave_days"}
        for field in list(request.data.keys()):
            if field not in editable:
                request.data.pop(field, None)
        response = super().update(request, *args, **kwargs)
        instance.refresh_from_db()
        recalculate_payslip(instance)
        instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=["post"])
    def recalculate(self, request, pk=None):
        payslip = self.get_object()
        try:
            payslip = recalculate_payslip(payslip)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(payslip).data)


class PayrollItemViewSet(_BaseAuditedViewSet):
    queryset = PayrollItem.objects.select_related("employee", "item_type_ref").all()
    serializer_class = PayrollItemSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        employee_id = self.request.query_params.get("employee")
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        item_type = self.request.query_params.get("item_type")
        if item_type:
            qs = qs.filter(item_type=item_type)
        return qs


class PayrollItemTypeViewSet(_BaseAuditedViewSet):
    queryset = PayrollItemType.objects.all()
    serializer_class = PayrollItemTypeSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        item_type = self.request.query_params.get("item_type")
        if item_type:
            qs = qs.filter(item_type=item_type)
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ("1", "true", "yes"))
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
        return qs

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_system_managed:
            return Response(
                {"detail": "System-managed payroll item types cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if instance.employee_items.exists():
            return Response(
                {
                    "detail": (
                        "This payroll item type is in use by one or more employees and cannot be deleted. "
                        "Mark it inactive instead."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class TaxRuleViewSet(_BaseAuditedViewSet):
    queryset = TaxRule.objects.all()
    serializer_class = TaxRuleSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
        return qs

    @action(detail=False, methods=["post"])
    def preview(self, request):
        """Preview a tax computation without persisting.

        Body: {gross, basic, allowances, deductions, rules: [<id>...]?}
        """
        from datetime import date as _date
        from decimal import Decimal

        rule_ids = request.data.get("rules") or []
        rules = list(TaxRule.objects.filter(id__in=rule_ids)) if rule_ids else list(
            TaxRule.objects.filter(is_active=True)
        )
        try:
            gross = Decimal(str(request.data.get("gross", "0")))
            basic = Decimal(str(request.data.get("basic", gross)))
            allowances = Decimal(str(request.data.get("allowances", "0")))
            deductions = Decimal(str(request.data.get("deductions", "0")))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid numeric input."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            total, breakdown = apply_tax_rules(
                rules=rules,
                gross=gross,
                basic=basic,
                allowances=allowances,
                deductions=deductions,
                on_date=_date.today(),
            )
        except Exception as exc:  # noqa: BLE001 - surface formula errors verbatim
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"total": str(total), "breakdown": breakdown})


class EmployeeTaxRuleOverrideViewSet(_BaseAuditedViewSet):
    queryset = EmployeeTaxRuleOverride.objects.select_related("rule", "employee").all()
    serializer_class = EmployeeTaxRuleOverrideSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        employee_id = self.request.query_params.get("employee")
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        rule_id = self.request.query_params.get("rule")
        if rule_id:
            qs = qs.filter(rule_id=rule_id)
        return qs

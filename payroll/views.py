"""Payroll viewsets."""

from __future__ import annotations

from io import BytesIO
from decimal import Decimal

from django.db.models import Q
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from hr.models import Employee

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
    get_formula_guide,
    preview_formula_amount,
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

    @action(detail=True, methods=["post"], url_path="sync-employees")
    def sync_employees(self, request, pk=None):
        """Assign this pay schedule to all employees.

        Optional body:
        - `only_without_schedule`: when true, only employees with no pay schedule are updated.
        """
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

    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        payslip = self.get_object()
        if payslip.payroll_run.status != PayrollRun.Status.PAID:
            return Response(
                {"detail": "Payslip PDF is available only when payroll run status is PAID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        buf = BytesIO()
        pdf = canvas.Canvas(buf, pagesize=A4)
        width, height = A4
        left = 18 * mm
        right = width - (18 * mm)
        y = height - (18 * mm)

        employee_name = f"{payslip.employee.first_name} {payslip.employee.last_name}".strip()
        period_name = payslip.payroll_run.period.name
        currency_code = payslip.currency.code

        def money(value: Decimal | int | float | str) -> str:
            return f"{currency_code} {Decimal(str(value)).quantize(Decimal('0.01'))}"

        def line(label: str, value: str):
            nonlocal y
            pdf.setFont("Helvetica", 10)
            pdf.setFillColor(colors.black)
            pdf.drawString(left, y, label)
            pdf.drawRightString(right, y, value)
            y -= 6 * mm

        pdf.setTitle(f"Payslip {employee_name}")
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(left, y, "Payslip")
        y -= 8 * mm

        pdf.setFont("Helvetica", 10)
        pdf.setFillColor(colors.grey)
        pdf.drawString(left, y, f"Employee: {employee_name or payslip.employee.employee_number}")
        y -= 5 * mm
        pdf.drawString(left, y, f"Employee No: {payslip.employee.employee_number}")
        y -= 5 * mm
        pdf.drawString(left, y, f"Period: {period_name}")
        y -= 5 * mm
        pdf.drawString(left, y, f"Generated: {payslip.generated_at:%Y-%m-%d %H:%M}")
        y -= 8 * mm

        pdf.setStrokeColor(colors.HexColor("#E5E7EB"))
        pdf.line(left, y, right, y)
        y -= 8 * mm

        line("Gross Pay", money(payslip.gross_pay))
        line("Tax", money(payslip.tax))
        line("Deductions", money(payslip.deductions))
        line("Net Pay", money(payslip.net_pay))

        def draw_breakdown(title: str, rows: list[dict], value_key: str = "amount"):
            nonlocal y
            if y < 50 * mm:
                pdf.showPage()
                y = height - (18 * mm)
            pdf.setFillColor(colors.black)
            pdf.setFont("Helvetica-Bold", 11)
            pdf.drawString(left, y, title)
            y -= 6 * mm
            if not rows:
                pdf.setFillColor(colors.grey)
                pdf.setFont("Helvetica", 9)
                pdf.drawString(left, y, "No entries")
                y -= 6 * mm
                return
            for row in rows:
                if y < 35 * mm:
                    pdf.showPage()
                    y = height - (18 * mm)
                name = str(row.get("name") or row.get("rule") or "-")
                code = row.get("code")
                label = f"{name} ({code})" if code else name
                amount = row.get(value_key)
                pdf.setFillColor(colors.black)
                pdf.setFont("Helvetica", 9)
                pdf.drawString(left, y, label)
                pdf.drawRightString(right, y, money(amount or 0))
                y -= 5 * mm
            y -= 2 * mm

        breakdown = payslip.breakdown or {}
        draw_breakdown("Allowances", breakdown.get("allowances", []))
        draw_breakdown("Deductions", breakdown.get("deductions", []))
        draw_breakdown("Tax Breakdown", breakdown.get("tax", []))

        pdf.showPage()
        pdf.save()
        pdf_bytes = buf.getvalue()
        buf.close()

        safe_employee = (employee_name or payslip.employee.employee_number).replace(" ", "_")
        safe_period = period_name.replace(" ", "_")
        filename = f"payslip_{safe_employee}_{safe_period}.pdf"

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


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

    @action(detail=False, methods=["get"], url_path="formula-guide")
    def formula_guide(self, request):
        return Response(get_formula_guide())

    @action(detail=False, methods=["post"], url_path="preview-formula")
    def preview_formula(self, request):
        try:
            result = preview_formula_amount(
                calculation_type=str(request.data.get("calculation_type", "flat")),
                value=request.data.get("value", "0"),
                formula=str(request.data.get("formula", "") or ""),
                applies_to=str(request.data.get("applies_to", "basic")),
                gross=Decimal(str(request.data.get("gross", "1000"))),
                basic=Decimal(str(request.data.get("basic", request.data.get("gross", "1000")))),
                allowances=Decimal(str(request.data.get("allowances", "0"))),
                deductions=Decimal(str(request.data.get("deductions", "0"))),
            )
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class TaxRuleViewSet(_BaseAuditedViewSet):
    queryset = TaxRule.objects.all()
    serializer_class = TaxRuleSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
        return qs

    @action(detail=False, methods=["get"], url_path="formula-guide")
    def formula_guide(self, request):
        return Response(get_formula_guide())

    @action(detail=False, methods=["post"], url_path="preview-formula")
    def preview_formula(self, request):
        try:
            result = preview_formula_amount(
                calculation_type=str(request.data.get("calculation_type", "flat")),
                value=request.data.get("value", "0"),
                formula=str(request.data.get("formula", "") or ""),
                applies_to=str(request.data.get("applies_to", "gross")),
                gross=Decimal(str(request.data.get("gross", "1000"))),
                basic=Decimal(str(request.data.get("basic", request.data.get("gross", "1000")))),
                allowances=Decimal(str(request.data.get("allowances", "0"))),
                deductions=Decimal(str(request.data.get("deductions", "0"))),
            )
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    @action(detail=True, methods=["post"], url_path="sync-employees")
    def sync_employees(self, request, pk=None):
        rule = self.get_object()
        scope = str(request.data.get("scope", "all"))
        employee_ids = request.data.get("employee_ids") or []
        employee_identifiers = request.data.get("employee_identifiers") or []
        department_id = request.data.get("department_id")
        position_id = request.data.get("position_id")

        qs = Employee.objects.all()
        if scope == "selected":
            selector = Q()
            if employee_ids:
                selector |= Q(id__in=employee_ids)
            if employee_identifiers:
                selector |= Q(id_number__in=employee_identifiers)
            qs = qs.filter(selector) if selector else qs.none()
        elif scope == "department":
            if not department_id:
                return Response({"detail": "department_id is required for department scope."}, status=status.HTTP_400_BAD_REQUEST)
            qs = qs.filter(department_id=department_id)
        elif scope == "position":
            if not position_id:
                return Response({"detail": "position_id is required for position scope."}, status=status.HTTP_400_BAD_REQUEST)
            qs = qs.filter(position_id=position_id)
        elif scope != "all":
            return Response({"detail": "Invalid scope. Use all, selected, department, or position."}, status=status.HTTP_400_BAD_REQUEST)

        targeted = qs.count()
        updated = 0
        for employee in qs.iterator():
            if not employee.tax_rules.filter(id=rule.id).exists():
                employee.tax_rules.add(rule)
                updated += 1

        return Response(
            {
                "detail": f"Assigned tax rule '{rule.name}' to {updated} employee(s).",
                "targeted": targeted,
                "updated": updated,
                "rule_id": str(rule.id),
                "scope": scope,
            },
            status=status.HTTP_200_OK,
        )

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

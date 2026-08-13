from collections import OrderedDict
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count
from rest_framework import serializers

from .enums import CalculationType, DeductionSourceType, PaymentMethod, SalaryAdvanceRepaymentMethod, SalaryAdvanceRepaymentStatus, StaffWardSponsorshipStatus, TargetAmountSource
from .services import (
    _build_staff_ward_student_allocation,
    _build_staff_ward_repayment_schedule,
    _staff_ward_sponsorship_period_start,
    create_payroll_v2_run,
    generate_payroll_item_rule_name,
)
from .obligation_services import (
    calculate_employee_contribution_amount,
    calculate_sponsorship_coverage_amount,
    evaluate_employee_obligation_eligibility,
    to_money,
    validate_employee_obligation_eligibility,
)
from .models import (
    EmployeeCompensation,
    EmployeePayrollItem,
    EmployeeWard,
    PayrollCatalogItem,
    PayrollCatalogItemRule,
    PayrollDeductionInstallment,
    PayrollDeductionSchedule,
    PayrollEmployeeItem,
    PayrollLineItem,
    PayrollPayslipTemplate,
    PayrollPeriod,
    PaySchedule,
    PayrollRunRecord,
    PayrollSettings,
    PayrollTableView,
    SalaryAdvance,
    SalaryAdvancePayment,
    StaffWardSponsorship,
    StaffWardSponsorshipPolicy,
    StaffWardSponsorshipStudent,
)
from .settings_services import get_tenant_payroll_settings


class EmployeeDisplaySerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.SerializerMethodField()
    id_number = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    position_title = serializers.SerializerMethodField()

    def get_name(self, obj):
        if hasattr(obj, "get_full_name"):
            value = obj.get_full_name()
            if value:
                return value
        parts = [getattr(obj, "first_name", ""), getattr(obj, "middle_name", ""), getattr(obj, "last_name", "")]
        return " ".join([p for p in parts if p]).strip() or str(obj)

    def get_id_number(self, obj):
        return getattr(obj, "id_number", None)

    def get_department_name(self, obj):
        department = getattr(obj, "department", None)
        return getattr(department, "name", None) if department else None

    def get_position_title(self, obj):
        position = getattr(obj, "position", None)
        return getattr(position, "title", None) if position else None


class EmployeeCompensationSerializer(serializers.ModelSerializer):
    employee_display = EmployeeDisplaySerializer(source="employee", read_only=True)
    currency_code = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeCompensation
        fields = [
            "id",
            "employee",
            "employee_display",
            "pay_type",
            "base_amount",
            "hourly_rate",
            "daily_rate",
            "annual_salary",
            "currency",
            "currency_code",
            "effective_start_date",
            "effective_end_date",
            "is_active",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["annual_salary", "created_at", "updated_at"]

    def get_currency_code(self, obj):
        currency = getattr(obj, "currency", None)
        return getattr(currency, "code", None) if currency else None


class PayrollItemRulePreviewSerializer(serializers.Serializer):
    calculation_type = serializers.ChoiceField(choices=CalculationType.choices, default=CalculationType.FLAT)
    value = serializers.DecimalField(max_digits=14, decimal_places=4, required=False, default=Decimal("0"))
    formula = serializers.CharField(required=False, allow_blank=True, default="")
    target_amount_source = serializers.ChoiceField(
        choices=TargetAmountSource.choices,
        default=TargetAmountSource.BASIC_SALARY,
    )
    target_min_amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
    target_max_amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
    calculation_limit = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
    priority = serializers.IntegerField(required=False, default=100)
    is_active = serializers.BooleanField(required=False, default=True)


class PayrollItemRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollCatalogItemRule
        fields = [
            "id",
            "payroll_item",
            "name",
            "calculation_type",
            "value",
            "formula",
            "target_amount_source",
            "target_min_amount",
            "target_max_amount",
            "calculation_limit",
            "effective_start_date",
            "effective_end_date",
            "priority",
            "is_active",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["name", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["name"] = generate_payroll_item_rule_name(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        snapshot = {
            "calculation_type": validated_data.get("calculation_type", instance.calculation_type),
            "value": validated_data.get("value", instance.value),
            "formula": validated_data.get("formula", instance.formula),
            "target_amount_source": validated_data.get("target_amount_source", instance.target_amount_source),
            "target_min_amount": validated_data.get("target_min_amount", instance.target_min_amount),
            "target_max_amount": validated_data.get("target_max_amount", instance.target_max_amount),
        }
        validated_data["name"] = generate_payroll_item_rule_name(snapshot)
        return super().update(instance, validated_data)


class PayrollItemSerializer(serializers.ModelSerializer):
    rules = PayrollItemRuleSerializer(many=True, read_only=True)

    class Meta:
        model = PayrollCatalogItem
        fields = [
            "id",
            "name",
            "code",
            "line_type",
            "is_taxable",
            "priority",
            "is_active",
            "description",
            "rules",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class EmployeePayrollItemSerializer(serializers.ModelSerializer):
    employee_display = EmployeeDisplaySerializer(source="employee", read_only=True)
    payroll_item_display = PayrollItemSerializer(source="payroll_item", read_only=True)

    class Meta:
        model = EmployeePayrollItem
        fields = [
            "id",
            "employee",
            "employee_display",
            "payroll_item",
            "payroll_item_display",
            "name_override",
            "calculation_type",
            "value",
            "formula",
            "target_amount_source",
            "calculation_limit",
            "is_taxable",
            "is_recurring",
            "frequency",
            "start_date",
            "end_date",
            "is_active",
            "priority",
            "source_type",
            "source_id",
            "calculation_overridden",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def _apply_calculation_override_flag(self, validated_data, instance=None):
        if validated_data.get("calculation_overridden") is False:
            validated_data["calculation_overridden"] = False
            return validated_data
        if validated_data.get("calculation_overridden") is True:
            return validated_data

        calc_type = validated_data.get(
            "calculation_type",
            getattr(instance, "calculation_type", CalculationType.FLAT) if instance else CalculationType.FLAT,
        )
        value = validated_data.get(
            "value",
            getattr(instance, "value", Decimal("0")) if instance else Decimal("0"),
        )
        formula = validated_data.get(
            "formula",
            getattr(instance, "formula", "") if instance else "",
        )
        limit = validated_data.get(
            "calculation_limit",
            getattr(instance, "calculation_limit", None) if instance else None,
        )

        if (
            calc_type != CalculationType.FLAT
            or (value or Decimal("0")) != Decimal("0")
            or (formula or "").strip()
            or limit is not None
        ):
            validated_data["calculation_overridden"] = True
        elif instance is None:
            validated_data.setdefault("calculation_overridden", False)

        return validated_data

    def create(self, validated_data):
        validated_data = self._apply_calculation_override_flag(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data = self._apply_calculation_override_flag(validated_data, instance)
        return super().update(instance, validated_data)


class PayrollLineItemSerializer(serializers.ModelSerializer):
    column_key = serializers.SerializerMethodField()

    class Meta:
        model = PayrollLineItem
        fields = [
            "id",
            "payroll_employee_item",
            "payroll_item",
            "employee_payroll_item",
            "payroll_item_rule",
            "line_type",
            "name",
            "code",
            "amount",
            "calculation_type",
            "target_amount_source",
            "is_taxable",
            "is_recurring",
            "frequency",
            "source_type",
            "source_id",
            "metadata",
            "description",
            "column_key",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_column_key(self, obj):
        if obj.payroll_item_id:
            return f"item:{obj.payroll_item_id}"
        code = (obj.code or "").strip()
        if code:
            return f"code:{code.lower()}"
        return f"line:{obj.id}"


class PayrollEmployeeItemSerializer(serializers.ModelSerializer):
    employee_display = EmployeeDisplaySerializer(source="employee", read_only=True)
    line_items = PayrollLineItemSerializer(many=True, read_only=True)
    payroll_run_period_name = serializers.SerializerMethodField()
    payroll_run_status = serializers.CharField(source="payroll.status", read_only=True)
    payroll_number = serializers.CharField(source="payroll.payroll_number", read_only=True)
    pay_period_start = serializers.DateField(source="payroll.pay_period_start", read_only=True)
    pay_period_end = serializers.DateField(source="payroll.pay_period_end", read_only=True)
    payment_date = serializers.DateField(source="payroll.payment_date", read_only=True)
    pay_schedule_frequency = serializers.SerializerMethodField()

    class Meta:
        model = PayrollEmployeeItem
        fields = [
            "id",
            "payroll",
            "payroll_run_period_name",
            "payroll_run_status",
            "payroll_number",
            "pay_period_start",
            "pay_period_end",
            "payment_date",
            "pay_schedule_frequency",
            "employee",
            "employee_display",
            "compensation",
            "basic_salary",
            "gross_pay",
            "taxable_income",
            "total_tax",
            "total_deductions",
            "total_benefits",
            "total_reimbursements",
            "net_pay",
            "payment_method",
            "payment_status",
            "notes",
            "line_items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "gross_pay",
            "taxable_income",
            "total_tax",
            "total_deductions",
            "total_benefits",
            "total_reimbursements",
            "net_pay",
            "created_at",
            "updated_at",
        ]

    def get_payroll_run_period_name(self, obj):
        run = obj.payroll
        return f"{run.pay_period_start} – {run.pay_period_end}"

    def get_pay_schedule_frequency(self, obj):
        from payroll_v2.schedule_services import get_pay_schedule

        schedule = get_pay_schedule(getattr(obj.payroll, "pay_schedule_id", None))
        return schedule.frequency if schedule else None


class PayScheduleSerializer(serializers.ModelSerializer):
    currency_code = serializers.CharField(source="currency.code", read_only=True)
    currency_symbol = serializers.CharField(source="currency.symbol", read_only=True)
    has_runs = serializers.SerializerMethodField()

    class Meta:
        model = PaySchedule
        fields = [
            "id",
            "name",
            "frequency",
            "anchor_date",
            "currency",
            "currency_code",
            "currency_symbol",
            "payment_day_offset",
            "overtime_multiplier",
            "is_default",
            "is_active",
            "has_runs",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "has_runs"]

    def get_has_runs(self, obj):
        if obj.periods.filter(payroll_runs__isnull=False).exists():
            return True
        return PayrollRunRecord.objects.filter(pay_schedule_id=obj.id).exists()

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.periods.exists():
            new_currency = attrs.get("currency", instance.currency)
            if new_currency != instance.currency:
                raise serializers.ValidationError(
                    {"currency": "Currency cannot change after periods exist on this schedule."}
                )
        return attrs


class PayrollPeriodSerializer(serializers.ModelSerializer):
    schedule_name = serializers.CharField(source="schedule.name", read_only=True)
    currency_code = serializers.CharField(source="schedule.currency.code", read_only=True)

    class Meta:
        model = PayrollPeriod
        fields = [
            "id",
            "schedule",
            "schedule_name",
            "currency_code",
            "name",
            "start_date",
            "end_date",
            "payment_date",
            "is_closed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "is_closed"]


class PayrollRunListSerializer(serializers.ModelSerializer):
    employee_count = serializers.SerializerMethodField()
    currency_code = serializers.CharField(source="currency.code", read_only=True)
    currency_symbol = serializers.CharField(source="currency.symbol", read_only=True)
    bank_account_name = serializers.CharField(source="bank_account.account_name", read_only=True)
    pay_schedule_name = serializers.SerializerMethodField()
    pay_schedule_frequency = serializers.SerializerMethodField()
    period_name = serializers.CharField(source="payroll_period.name", read_only=True)

    class Meta:
        model = PayrollRunRecord
        fields = [
            "id",
            "payroll_number",
            "payroll_type",
            "pay_schedule",
            "pay_schedule_name",
            "pay_schedule_frequency",
            "payroll_period",
            "period_name",
            "pay_period_start",
            "pay_period_end",
            "payment_date",
            "status",
            "currency",
            "currency_code",
            "currency_symbol",
            "bank_account",
            "bank_account_name",
            "employee_count",
            "gross_pay_total",
            "deduction_total",
            "tax_total",
            "benefit_total",
            "reimbursement_total",
            "net_pay_total",
            "approved_by",
            "approved_at",
            "paid_at",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "payroll_period",
            "gross_pay_total",
            "deduction_total",
            "tax_total",
            "benefit_total",
            "reimbursement_total",
            "net_pay_total",
            "approved_by",
            "approved_at",
            "paid_at",
            "created_at",
            "updated_at",
        ]


    def get_employee_count(self, obj):
        from payroll_v2.enums import PayrollStatus

        if obj.status == PayrollStatus.PAID:
            snapshot = getattr(obj, "paid_table_snapshot", None) or {}
            totals = snapshot.get("totals") or {}
            line_count = totals.get("line_count")
            if line_count is not None:
                return int(line_count)
            rows = snapshot.get("rows") or []
            if rows:
                return len(rows)
            employee_items = snapshot.get("employee_items") or []
            if employee_items:
                return len(employee_items)
        annotated = getattr(obj, "employee_count", None)
        if annotated is not None:
            return annotated
        return obj.employee_items.count()

    def get_pay_schedule_name(self, obj):
        from payroll_v2.schedule_services import get_pay_schedule

        schedule = get_pay_schedule(obj.pay_schedule_id)
        return schedule.name if schedule else None

    def get_pay_schedule_frequency(self, obj):
        from payroll_v2.schedule_services import get_pay_schedule

        schedule = get_pay_schedule(obj.pay_schedule_id)
        return schedule.frequency if schedule else None


class PayrollRunWriteSerializer(PayrollRunListSerializer):
    period_name = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta(PayrollRunListSerializer.Meta):
        read_only_fields = PayrollRunListSerializer.Meta.read_only_fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is not None and "pay_schedule" in self.fields:
            self.fields["pay_schedule"].read_only = True

    def validate(self, attrs):
        if self.instance is None and not attrs.get("pay_schedule"):
            raise serializers.ValidationError({"pay_schedule": "Pay schedule is required."})
        return attrs

    def create(self, validated_data):
        period_name = validated_data.pop("period_name", None)
        created_by = validated_data.pop("created_by", None)
        updated_by = validated_data.pop("updated_by", None)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return create_payroll_v2_run(
            period_name=period_name,
            created_by=created_by or user,
            updated_by=updated_by or user,
            **validated_data,
        )


PAYROLL_V2_TABLE_COLUMN_KEY_ALIASES = {
    "deductions": "total_deductions",
    "deduction_total": "total_deductions",
    "deductions_total": "total_deductions",
    "tax": "total_tax",
    "tax_total": "total_tax",
    "gross": "gross_pay",
    "gross_total": "gross_pay",
    "gross_pay_total": "gross_pay",
    "net": "net_pay",
    "net_pay_total": "net_pay",
    "benefits": "total_benefits",
    "benefit_total": "total_benefits",
    "reimbursements": "total_reimbursements",
    "reimbursement_total": "total_reimbursements",
}


def normalize_payroll_v2_table_column_key(key):
    if not key:
        return key
    return PAYROLL_V2_TABLE_COLUMN_KEY_ALIASES.get(key, key)


class PayrollRunDetailSerializer(PayrollRunListSerializer):
    employee_items = serializers.SerializerMethodField()
    columns = serializers.SerializerMethodField()
    rows = serializers.SerializerMethodField()
    table_view_snapshot = serializers.JSONField(read_only=True)
    payslip_template_snapshot = serializers.JSONField(read_only=True)
    paid_table_snapshot = serializers.JSONField(read_only=True)
    totals = serializers.SerializerMethodField()

    class Meta(PayrollRunListSerializer.Meta):
        fields = PayrollRunListSerializer.Meta.fields + [
            "table_view",
            "table_view_snapshot",
            "payslip_template",
            "payslip_template_snapshot",
            "paid_table_snapshot",
            "columns",
            "rows",
            "totals",
            "employee_items",
        ]

    def _paid_snapshot(self, obj):
        snapshot = getattr(obj, "paid_table_snapshot", None) or {}
        if not snapshot or not snapshot.get("rows"):
            return None
        from payroll_v2.enums import PayrollStatus

        if obj.status != PayrollStatus.PAID:
            return None
        return snapshot

    def get_employee_items(self, obj):
        paid_snapshot = self._paid_snapshot(obj)
        if paid_snapshot is not None:
            employee_items = paid_snapshot.get("employee_items")
            if employee_items is not None:
                return employee_items
            return []
        return PayrollEmployeeItemSerializer(
            obj.employee_items.prefetch_related("line_items").all(),
            many=True,
        ).data

    def get_totals(self, obj):
        paid_snapshot = self._paid_snapshot(obj)
        if paid_snapshot and paid_snapshot.get("totals"):
            return paid_snapshot["totals"]
        return {
            "gross": str(obj.gross_pay_total or Decimal("0.00")),
            "deductions": str(obj.deduction_total or Decimal("0.00")),
            "tax": str(obj.tax_total or Decimal("0.00")),
            "benefits": str(obj.benefit_total or Decimal("0.00")),
            "reimbursements": str(obj.reimbursement_total or Decimal("0.00")),
            "net": str(obj.net_pay_total or Decimal("0.00")),
        }

    def _base_columns(self):
        return [
            {"key": "employee", "label": "Employee", "source": "system", "visible": True, "order": 10, "locked": True},
            {"key": "employee_id_number", "label": "Employee ID", "source": "employee", "visible": False, "order": 15},
            {"key": "department", "label": "Department", "source": "employee", "visible": False, "order": 16},
            {"key": "position", "label": "Position", "source": "employee", "visible": False, "order": 17},
            {"key": "basic_salary", "label": "Basic Salary", "source": "system", "visible": False, "order": 20},
            {"key": "taxable_income", "label": "Taxable Income", "source": "system", "visible": False, "order": 25},
            {"key": "gross_pay", "label": "Gross Pay", "source": "system", "visible": True, "order": 900},
            {"key": "total_tax", "label": "Total Tax", "source": "system", "visible": True, "order": 910},
            {"key": "total_deductions", "label": "Total Deductions", "source": "system", "visible": True, "order": 920},
            {"key": "total_benefits", "label": "Total Benefits", "source": "system", "visible": False, "order": 925},
            {"key": "total_reimbursements", "label": "Total Reimbursements", "source": "system", "visible": False, "order": 928},
            {"key": "net_pay", "label": "Net Pay", "source": "system", "visible": True, "order": 930},
            {"key": "payment_status", "label": "Status", "source": "system", "visible": True, "order": 940},
        ]

    def get_columns(self, obj):
        paid_snapshot = self._paid_snapshot(obj)
        if paid_snapshot and paid_snapshot.get("columns"):
            return paid_snapshot["columns"]

        columns = OrderedDict((c["key"], dict(c)) for c in self._base_columns())

        line_qs = PayrollLineItem.objects.filter(
            payroll_employee_item__payroll=obj,
            payroll_item_id__isnull=False,
        ).select_related("payroll_item")
        seen_keys = set()
        for line in line_qs:
            key = f"item:{line.payroll_item_id}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            columns[key] = {
                "key": key,
                "label": line.name,
                "source": "payroll_item",
                "line_type": line.line_type,
                "visible": False,
                "order": line.payroll_item.priority if line.payroll_item else 500,
                "payroll_item_id": str(line.payroll_item_id),
            }

        request = self.context.get("request")
        table_view_id = request.query_params.get("table_view_id") if request else None
        view_columns = []
        if table_view_id:
            view = PayrollTableView.objects.filter(id=table_view_id, active=True).first()
            view_columns = view.columns if view else []
        elif obj.table_view_snapshot:
            view_columns = (obj.table_view_snapshot or {}).get("columns") or []
        elif obj.table_view_id:
            view = getattr(obj, "table_view", None)
            view_columns = view.columns if view else []

        for config in view_columns:
            raw_key = config.get("key")
            if not raw_key:
                continue
            key = normalize_payroll_v2_table_column_key(raw_key)
            merged_config = {**config, "key": key}
            current = columns.get(key, {"key": key, "source": merged_config.get("source", "custom")})
            current.update(merged_config)
            columns[key] = current

        return sorted(
            [c for c in columns.values() if c.get("visible", True)],
            key=lambda c: (c.get("order", 999999), c.get("label") or c.get("key")),
        )

    @staticmethod
    def _row_amount(value):
        if value is None:
            return str(Decimal("0.00"))
        return str(value)

    def get_rows(self, obj):
        paid_snapshot = self._paid_snapshot(obj)
        if paid_snapshot and paid_snapshot.get("rows"):
            return paid_snapshot["rows"]

        rows = []
        for item in obj.employee_items.prefetch_related("line_items", "employee").all():
            dynamic_values = {}
            for line in item.line_items.all():
                if line.payroll_item_id:
                    key = f"item:{line.payroll_item_id}"
                elif line.code:
                    key = f"code:{line.code.lower()}"
                else:
                    key = f"line:{line.id}"
                dynamic_values[key] = (dynamic_values.get(key, Decimal("0.00")) + line.amount)
            rows.append(
                {
                    "id": str(item.id),
                    "employee": EmployeeDisplaySerializer(item.employee).data,
                    "basic_salary": self._row_amount(item.basic_salary),
                    "gross_pay": self._row_amount(item.gross_pay),
                    "taxable_income": self._row_amount(item.taxable_income),
                    "total_tax": self._row_amount(item.total_tax),
                    "total_deductions": self._row_amount(item.total_deductions),
                    "total_benefits": self._row_amount(item.total_benefits),
                    "total_reimbursements": self._row_amount(item.total_reimbursements),
                    "net_pay": self._row_amount(item.net_pay),
                    "payment_status": item.payment_status,
                    "dynamic_values": {k: str(v) for k, v in dynamic_values.items()},
                }
            )
        return rows


class GeneratePayrollSerializer(serializers.Serializer):
    employee_ids = serializers.ListField(child=serializers.CharField(), required=False, allow_empty=True)
    replace_existing = serializers.BooleanField(default=True)
    table_view_id = serializers.CharField(required=False, allow_blank=True)


class PayrollRunStatusActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)


class WorkflowReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class DeductionInstallmentAdjustSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    reason = serializers.CharField(required=False, allow_blank=True)


class DeductionInstallmentAutoAdjustSerializer(serializers.Serializer):
    max_allowed_amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    reason = serializers.CharField(required=False, allow_blank=True)


class PayrollObligationEligibilityPreviewSerializer(serializers.Serializer):
    employee = serializers.CharField()
    obligation_type = serializers.ChoiceField(
        choices=[
            DeductionSourceType.STAFF_WARD_SPONSORSHIP,
            DeductionSourceType.SALARY_ADVANCE,
        ]
    )
    requested_periodic_deduction = serializers.DecimalField(max_digits=16, decimal_places=2, required=False, default=Decimal("0.00"))
    requested_amount = serializers.DecimalField(max_digits=16, decimal_places=2, required=False, allow_null=True)
    requested_installments = serializers.IntegerField(required=False, min_value=1)
    repayment_method = serializers.ChoiceField(
        choices=[SalaryAdvanceRepaymentMethod.EQUAL_SPLIT, SalaryAdvanceRepaymentMethod.FIXED_INSTALLMENT],
        required=False,
    )
    fixed_installment_amount = serializers.DecimalField(max_digits=16, decimal_places=2, required=False, allow_null=True)
    exclude_source_id = serializers.CharField(required=False, allow_blank=True)


class WardSponsorshipWindowPreviewSerializer(serializers.Serializer):
    academic_year = serializers.CharField()
    start_period = serializers.CharField(required=False, allow_blank=True)
    total_sponsorship_amount = serializers.DecimalField(max_digits=16, decimal_places=2, required=False, default=Decimal("0.00"))


class SalaryAdvanceCancellationSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, allow_blank=False)


class SalaryAdvancePaymentRecordSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    payment_date = serializers.DateField(required=False)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices, default=PaymentMethod.OTHER)
    reference = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class SalaryAdvancePaymentSerializer(serializers.ModelSerializer):
    finance_transaction_id = serializers.CharField(source="finance_transaction.id", read_only=True)
    finance_transaction_reference = serializers.CharField(source="finance_transaction.reference_number", read_only=True)
    finance_transaction_status = serializers.CharField(source="finance_transaction.status", read_only=True)
    finance_transaction_completed_at = serializers.DateTimeField(source="finance_transaction.completed_at", read_only=True)

    class Meta:
        model = SalaryAdvancePayment
        fields = [
            "id",
            "salary_advance",
            "finance_transaction",
            "finance_transaction_id",
            "finance_transaction_reference",
            "finance_transaction_status",
            "finance_transaction_completed_at",
            "payment_date",
            "amount",
            "payment_method",
            "reference",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class PayrollTableViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollTableView
        fields = [
            "id",
            "name",
            "description",
            "is_default",
            "is_system",
            "applies_to",
            "columns",
            "filters",
            "sorting",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_columns(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Columns must be a list.")
        for entry in value:
            if not isinstance(entry, dict) or not entry.get("key"):
                raise serializers.ValidationError("Each column requires a key.")
        return value


class PayrollPayslipTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollPayslipTemplate
        fields = [
            "id",
            "name",
            "description",
            "is_default",
            "is_system",
            "layout",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class StaffWardSponsorshipPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffWardSponsorshipPolicy
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "maximum_wards",
            "coverage_type",
            "coverage_value",
            "employee_contribution_type",
            "employee_contribution_value",
            "max_payroll_deduction_percent_of_gross",
            "min_net_pay_percent_of_gross",
            "max_total_voluntary_deduction_percent",
            "allow_auto_adjust",
            "allow_deduction_deferral",
            "requires_approval",
            "eligible_fee_types",
            "eligible_employment_types",
            "minimum_service_months",
            "effective_from",
            "effective_to",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class EmployeeWardSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeWard
        fields = [
            "id",
            "employee",
            "employee_name",
            "student",
            "student_name",
            "relationship_type",
            "is_verified",
            "verification_date",
            "verified_by",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() if obj.employee_id else None

    def get_student_name(self, obj):
        return obj.student.get_full_name() if obj.student_id else None


class StaffWardSponsorshipStudentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = StaffWardSponsorshipStudent
        fields = [
            "id",
            "sponsorship",
            "employee_ward",
            "student",
            "student_name",
            "enrollment",
            "eligible_fee_total",
            "school_covered_amount",
            "employee_responsibility_amount",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_student_name(self, obj):
        return obj.student.get_full_name() if obj.student_id else None

    def validate(self, attrs):
        attrs = super().validate(attrs)

        sponsorship = attrs.get("sponsorship") or getattr(self.instance, "sponsorship", None)
        if sponsorship is None:
            raise serializers.ValidationError({"sponsorship": "Sponsorship is required."})

        student = attrs.get("student") or getattr(self.instance, "student", None)
        if student is None:
            raise serializers.ValidationError({"student": "Student is required."})

        if sponsorship.academic_year_id:
            conflicting_rows = StaffWardSponsorshipStudent.objects.filter(
                student=student,
                sponsorship__academic_year_id=sponsorship.academic_year_id,
                sponsorship__status__in=[
                    StaffWardSponsorshipStatus.ACTIVE,
                    StaffWardSponsorshipStatus.COMPLETED,
                ],
            ).exclude(sponsorship_id=sponsorship.id)

            if self.instance is not None and getattr(self.instance, "pk", None):
                conflicting_rows = conflicting_rows.exclude(pk=self.instance.pk)

            if conflicting_rows.exists():
                raise serializers.ValidationError(
                    {
                        "student": (
                            "This student already has a Ward Sponsorship for the selected academic year "
                            "and cannot be sponsored again."
                        )
                    }
                )

        eligible_total = to_money(attrs.get("eligible_fee_total", getattr(self.instance, "eligible_fee_total", Decimal("0.00"))))
        if eligible_total <= Decimal("0.00"):
            raise serializers.ValidationError({"eligible_fee_total": "Eligible amount must be greater than zero."})

        policy = sponsorship.policy
        coverage_amount = calculate_sponsorship_coverage_amount(
            eligible_fee_total=eligible_total,
            coverage_type=policy.coverage_type,
            coverage_value=policy.coverage_value,
        )
        employee_amount = calculate_employee_contribution_amount(
            eligible_fee_total=eligible_total,
            school_covered_amount=coverage_amount,
            contribution_type=policy.employee_contribution_type,
            contribution_value=policy.employee_contribution_value,
        )

        attrs["eligible_fee_total"] = eligible_total
        attrs["school_covered_amount"] = coverage_amount
        attrs["employee_responsibility_amount"] = employee_amount
        return attrs

    def _refresh_sponsorship_totals(self, sponsorship: StaffWardSponsorship):
        rows = sponsorship.sponsorship_students.all()
        sponsored_total = to_money(sum((row.eligible_fee_total for row in rows), Decimal("0.00")))
        school_total = to_money(sum((row.school_covered_amount for row in rows), Decimal("0.00")))
        employee_total = to_money(sum((row.employee_responsibility_amount for row in rows), Decimal("0.00")))

        repayment_schedule = []
        monthly_recovery_amount = sponsored_total
        if sponsored_total > Decimal("0.00"):
            academic_year = getattr(sponsorship, "academic_year", None)
            year_end = getattr(academic_year, "end_date", None)
            if year_end:
                try:
                    start_period = getattr(sponsorship, "start_period", None) or _staff_ward_sponsorship_period_start(
                        sponsorship=sponsorship
                    )
                except Exception:
                    start_period = None

                if start_period is not None:
                    plan = _build_staff_ward_repayment_schedule(
                        total_amount=sponsored_total,
                        start_date=start_period.start_date,
                        end_date=year_end,
                    )
                    repayment_schedule = plan.get("rows") or []
                    monthly_recovery_amount = to_money(plan.get("monthly_deduction") or sponsored_total)

        sponsorship.total_sponsored_amount = sponsored_total
        sponsorship.school_contribution_amount = school_total
        sponsorship.employee_contribution_amount = employee_total
        sponsorship.payroll_recovery_amount = monthly_recovery_amount
        sponsorship.repayment_schedule = repayment_schedule
        sponsorship.student_allocation = _build_staff_ward_student_allocation(
            sponsorship=sponsorship,
            monthly_deduction=monthly_recovery_amount,
        )
        sponsorship.repayment_remaining_balance = sponsored_total
        sponsorship.repayment_paid_amount = Decimal("0.00")
        sponsorship.repayment_progress_percent = Decimal("0.00")
        sponsorship.save(
            update_fields=[
                "total_sponsored_amount",
                "school_contribution_amount",
                "employee_contribution_amount",
                "payroll_recovery_amount",
                "repayment_schedule",
                "student_allocation",
                "repayment_remaining_balance",
                "repayment_paid_amount",
                "repayment_progress_percent",
                "updated_at",
            ]
        )

    def create(self, validated_data):
        instance = super().create(validated_data)
        self._refresh_sponsorship_totals(instance.sponsorship)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        self._refresh_sponsorship_totals(instance.sponsorship)
        return instance


class StaffWardSponsorshipSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    id_number = serializers.CharField(source="employee.id_number", read_only=True)
    policy_name = serializers.CharField(source="policy.name", read_only=True)
    students = StaffWardSponsorshipStudentSerializer(many=True, source="sponsorship_students", read_only=True)

    class Meta:
        model = StaffWardSponsorship
        fields = [
            "id",
            "employee",
            "employee_name",
            "id_number",
            "policy",
            "policy_name",
            "academic_year",
            "application_date",
            "start_period",
            "end_period",
            "status",
            "total_sponsored_amount",
            "school_contribution_amount",
            "employee_contribution_amount",
            "payroll_recovery_amount",
            "repayment_schedule",
            "student_allocation",
            "repayment_paid_amount",
            "repayment_remaining_balance",
            "repayment_progress_percent",
            "review_notes",
            "rejection_reason",
            "approved_by",
            "approved_at",
            "completed_at",
            "students",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["approved_at", "completed_at", "created_at", "updated_at"]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() if obj.employee_id else None

    @staticmethod
    def _add_months(base_date: date, months: int) -> date:
        total_month_index = (base_date.year * 12 + (base_date.month - 1)) + max(0, int(months))
        year = total_month_index // 12
        month = (total_month_index % 12) + 1
        max_day = calendar.monthrange(year, month)[1]
        day = min(base_date.day, max_day)
        return date(year, month, day)

    @classmethod
    def _deadline_end_date(cls, *, academic_year_start: date, deadline_months: int) -> date:
        normalized = max(1, int(deadline_months or 1))
        return cls._add_months(academic_year_start, normalized) - timedelta(days=1)

    @classmethod
    def _month_index(cls, *, academic_year_start: date, target: date) -> int:
        return ((target.year - academic_year_start.year) * 12) + (target.month - academic_year_start.month) + 1

    def validate(self, attrs):
        attrs = super().validate(attrs)

        academic_year = attrs.get("academic_year") or getattr(self.instance, "academic_year", None)
        if academic_year is None:
            raise serializers.ValidationError({"academic_year": "Academic year is required."})

        application_date = attrs.get("application_date") or getattr(self.instance, "application_date", None) or date.today()
        if isinstance(application_date, str):
            application_date = date.fromisoformat(application_date)

        if not academic_year.start_date or not academic_year.end_date:
            raise serializers.ValidationError(
                {"academic_year": "Selected academic year must have valid start and end dates."}
            )
        if application_date < academic_year.start_date or application_date > academic_year.end_date:
            raise serializers.ValidationError(
                {"application_date": "Application date must fall within the selected academic year."}
            )

        request = self.context.get("request")
        settings = get_tenant_payroll_settings(user=getattr(request, "user", None))
        deadline_months = max(1, int(getattr(settings, "ward_sponsorship_application_deadline_months", 3) or 3))
        deadline_end = self._deadline_end_date(
            academic_year_start=academic_year.start_date,
            deadline_months=deadline_months,
        )

        if application_date > deadline_end:
            current_position = self._month_index(academic_year_start=academic_year.start_date, target=application_date)
            raise serializers.ValidationError(
                {
                    "application_date": (
                        "Ward sponsorship application window has closed for this academic year. "
                        f"Allowed in first {deadline_months} month(s) through {deadline_end.isoformat()}, "
                        f"but application month position is {current_position}."
                    )
                }
            )

        employee = attrs.get("employee") or getattr(self.instance, "employee", None)
        requested = attrs.get("payroll_recovery_amount")
        if employee is None or requested is None:
            return attrs

        requested_amount = to_money(requested)
        if requested_amount <= Decimal("0.00"):
            return attrs

        validate_employee_obligation_eligibility(
            employee=employee,
            payroll_settings=settings,
            obligation_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
            requested_periodic_deduction=requested_amount,
            exclude_source_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
            exclude_source_id=getattr(self.instance, "id", None),
        )
        return attrs


class SalaryAdvanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    completed_by_name = serializers.SerializerMethodField()
    cancelled_by_name = serializers.SerializerMethodField()
    id_number = serializers.CharField(source="employee.id_number", read_only=True)
    payments = SalaryAdvancePaymentSerializer(many=True, read_only=True)

    class Meta:
        model = SalaryAdvance
        fields = [
            "id",
            "employee",
            "employee_name",
            "id_number",
            "request_date",
            "amount",
            "approved_amount",
            "repayment_start_period",
            "repayment_method",
            "installment_amount",
            "amount_paid",
            "number_of_installments",
            "remaining_balance",
            "repayment_status",
            "status",
            "notes",
            "approved_by",
            "approved_by_name",
            "approved_at",
            "completed_by",
            "completed_by_name",
            "completed_at",
            "cancelled_by",
            "cancelled_by_name",
            "cancelled_at",
            "cancellation_reason",
            "payments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["approved_at", "completed_at", "cancelled_at", "created_at", "updated_at"]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() if obj.employee_id else None

    def get_approved_by_name(self, obj):
        return self._get_user_name(getattr(obj, "approved_by", None))

    def get_completed_by_name(self, obj):
        return self._get_user_name(getattr(obj, "completed_by", None))

    def get_cancelled_by_name(self, obj):
        return self._get_user_name(getattr(obj, "cancelled_by", None))

    def _get_user_name(self, user):
        if not user:
            return None
        if hasattr(user, "get_full_name"):
            full_name = (user.get_full_name() or "").strip()
            if full_name:
                return full_name
        full_name_attr = (getattr(user, "full_name", None) or "").strip()
        if full_name_attr:
            return full_name_attr
        name_parts = [
            (getattr(user, "first_name", None) or "").strip(),
            (getattr(user, "middle_name", None) or "").strip(),
            (getattr(user, "last_name", None) or "").strip(),
        ]
        name = " ".join(part for part in name_parts if part).strip()
        return name or None

    def validate(self, attrs):
        attrs = super().validate(attrs)

        request = self.context.get("request")
        settings = get_tenant_payroll_settings(user=getattr(request, "user", None))

        employee = attrs.get("employee") or getattr(self.instance, "employee", None)
        if employee is None:
            return attrs

        amount = to_money(attrs.get("amount", getattr(self.instance, "amount", Decimal("0.00"))))
        if amount <= Decimal("0.00"):
            raise serializers.ValidationError({"amount": "Amount must be greater than zero."})

        installments = int(attrs.get("number_of_installments", getattr(self.instance, "number_of_installments", 1)) or 1)
        if installments <= 0:
            raise serializers.ValidationError({"number_of_installments": "Installments must be at least 1."})

        repayment_method = attrs.get("repayment_method", getattr(self.instance, "repayment_method", SalaryAdvanceRepaymentMethod.EQUAL_SPLIT))
        installment_amount = to_money(
            attrs.get("installment_amount", getattr(self.instance, "installment_amount", Decimal("0.00")))
        )
        if repayment_method == SalaryAdvanceRepaymentMethod.FIXED_INSTALLMENT and installment_amount <= Decimal("0.00"):
            raise serializers.ValidationError({"installment_amount": "Installment amount must be greater than zero for fixed installment repayment."})

        if repayment_method == SalaryAdvanceRepaymentMethod.FIXED_INSTALLMENT and installment_amount > Decimal("0.00"):
            requested_periodic_deduction = installment_amount
        else:
            requested_periodic_deduction = to_money(amount / Decimal(str(installments)))

        min_service = int(getattr(settings, "salary_advance_min_service_months", 0) or 0)
        if min_service > 0:
            hire_date = getattr(employee, "hire_date", None)
            if hire_date:
                today = date.today()
                months = (today.year - hire_date.year) * 12 + (today.month - hire_date.month)
                if today.day < hire_date.day:
                    months -= 1
                if max(0, months) < min_service:
                    raise serializers.ValidationError(
                        {
                            "employee": (
                                f"Employee has {max(0, months)} month(s) of service. "
                                f"Minimum required is {min_service} month(s)."
                            )
                        }
                    )

        evaluation = evaluate_employee_obligation_eligibility(
            employee=employee,
            payroll_settings=settings,
            obligation_type=DeductionSourceType.SALARY_ADVANCE,
            requested_periodic_deduction=requested_periodic_deduction,
            requested_amount=amount,
            requested_installments=installments,
            repayment_method=repayment_method,
            fixed_installment_amount=installment_amount,
            exclude_source_type=DeductionSourceType.SALARY_ADVANCE,
            exclude_source_id=getattr(self.instance, "id", None),
        )
        if not evaluation["is_eligible"]:
            available_amount = evaluation.get("available_to_request_amount", "0.00")
            reasons = evaluation.get("reasons") or []
            summary = reasons[0] if reasons else "Requested amount is not currently eligible."
            raise serializers.ValidationError(
                {
                    "amount": (
                        f"{summary} Available to request is {available_amount}."
                    )
                }
            )
        return attrs


class PayrollDeductionInstallmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollDeductionInstallment
        fields = [
            "id",
            "deduction_schedule",
            "payroll_period",
            "scheduled_amount",
            "actual_amount",
            "status",
            "payroll_line",
            "adjustment_reason",
            "applied_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class PayrollDeductionScheduleSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    installments = PayrollDeductionInstallmentSerializer(many=True, read_only=True)

    class Meta:
        model = PayrollDeductionSchedule
        fields = [
            "id",
            "employee",
            "employee_name",
            "source_type",
            "source_id",
            "start_period",
            "end_period",
            "total_amount",
            "remaining_amount",
            "scheduled_amount",
            "status",
            "schedule_snapshot",
            "notes",
            "installments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() if obj.employee_id else None


class PayrollSettingsSerializer(serializers.ModelSerializer):
    transaction_type_name = serializers.CharField(
        source="transaction_type.name",
        read_only=True,
    )
    transaction_type_code = serializers.CharField(
        source="transaction_type.code",
        read_only=True,
    )
    salary_advance_repayment_ledger_account_code = serializers.CharField(
        source="salary_advance_repayment_ledger_account.code",
        read_only=True,
    )
    salary_advance_repayment_ledger_account_name = serializers.CharField(
        source="salary_advance_repayment_ledger_account.name",
        read_only=True,
    )

    class Meta:
        model = PayrollSettings
        fields = [
            "id",
            "transaction_type",
            "transaction_type_name",
            "transaction_type_code",
            "salary_advance_repayment_ledger_account",
            "salary_advance_repayment_ledger_account_code",
            "salary_advance_repayment_ledger_account_name",
            "payslip_table_column_labels",
            "show_leave_on_paystub",
            "allow_salary_advance",
            "allow_ward_sponsorship",
            "salary_advance_requires_approval",
            "salary_advance_default_repayment_method",
            "salary_advance_default_installments",
            "salary_advance_max_installments",
            "salary_advance_min_service_months",
            "maximum_ward_sponsorship_deduction_percent",
            "tax_reserve_percent",
            "minimum_take_home_pay_percent",
            "maximum_salary_advance_deduction_percent",
            "ward_sponsorship_application_deadline_months",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "transaction_type_name",
            "transaction_type_code",
            "salary_advance_repayment_ledger_account_code",
            "salary_advance_repayment_ledger_account_name",
            "created_at",
            "updated_at",
        ]

    def validate_payslip_table_column_labels(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Column labels must be an object.")
        cleaned: dict[str, str] = {}
        for key, raw in value.items():
            label = str(raw or "").strip()
            if label:
                cleaned[str(key)] = label
        return cleaned

    def validate_transaction_type(self, value):
        if value is None:
            return value
        if not value.is_active:
            raise serializers.ValidationError("Transaction type must be active.")
        if value.transaction_category != "expense":
            raise serializers.ValidationError("Payroll transaction type must be an expense type.")
        return value

    def validate_salary_advance_repayment_ledger_account(self, value):
        if value is None:
            return value
        if not value.is_active:
            raise serializers.ValidationError("Salary advance repayment account must be active.")
        if value.is_header:
            raise serializers.ValidationError("Salary advance repayment account cannot be a header account.")
        return value

    def validate_salary_advance_default_installments(self, value):
        if value is None:
            return value
        if value < 1:
            raise serializers.ValidationError("Default installments must be at least 1.")
        return value

    def validate_salary_advance_max_installments(self, value):
        if value is None:
            return value
        if value < 1:
            raise serializers.ValidationError("Maximum installments must be at least 1.")
        return value

    def _validate_percent(self, value, field_label: str):
        if value is None:
            return value
        parsed = Decimal(str(value))
        if parsed < Decimal("0") or parsed > Decimal("100"):
            raise serializers.ValidationError(f"{field_label} must be between 0 and 100.")
        return parsed

    def validate_maximum_ward_sponsorship_deduction_percent(self, value):
        return self._validate_percent(value, "Maximum ward sponsorship deduction percent")

    def validate_tax_reserve_percent(self, value):
        return self._validate_percent(value, "Tax reserve percent")

    def validate_minimum_take_home_pay_percent(self, value):
        return self._validate_percent(value, "Minimum take-home pay percent")

    def validate_maximum_salary_advance_deduction_percent(self, value):
        return self._validate_percent(value, "Maximum salary advance deduction percent")

    def validate_ward_sponsorship_application_deadline_months(self, value):
        if value is None:
            return value
        if int(value) < 1:
            raise serializers.ValidationError("Application deadline months must be at least 1.")
        if int(value) > 24:
            raise serializers.ValidationError("Application deadline months cannot exceed 24.")
        return int(value)


class SalaryAdvanceRepaymentRequestSerializer(serializers.Serializer):
    salary_advance = serializers.CharField()
    finance_transaction_id = serializers.CharField()
    finance_transaction_reference = serializers.CharField()
    finance_transaction_status = serializers.CharField()
    amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    payment_date = serializers.DateField()

    def validate(self, attrs):
        default_installments = attrs.get(
            "salary_advance_default_installments",
            getattr(self.instance, "salary_advance_default_installments", 1),
        )
        max_installments = attrs.get(
            "salary_advance_max_installments",
            getattr(self.instance, "salary_advance_max_installments", 12),
        )
        if default_installments and max_installments and default_installments > max_installments:
            raise serializers.ValidationError(
                {"salary_advance_default_installments": "Default installments cannot exceed the maximum."}
            )

        percent_fields = [
            "maximum_ward_sponsorship_deduction_percent",
            "tax_reserve_percent",
            "minimum_take_home_pay_percent",
            "maximum_salary_advance_deduction_percent",
        ]
        should_validate_percent_total = self.instance is None or any(field in attrs for field in percent_fields)

        if should_validate_percent_total:
            resolved_values = []
            for field in percent_fields:
                value = attrs.get(field, getattr(self.instance, field, Decimal("0")) if self.instance else Decimal("0"))
                resolved_values.append(Decimal(str(value or "0")))

            percent_total = sum(resolved_values, Decimal("0"))
            if percent_total != Decimal("100"):
                raise serializers.ValidationError(
                    {
                        "non_field_errors": [
                            (
                                "The sum of maximum ward sponsorship deduction %, tax reserve %, "
                                "minimum take-home pay %, and maximum salary advance deduction % "
                                "must equal 100%."
                            )
                        ]
                    }
                )
        return attrs

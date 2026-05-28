from collections import OrderedDict
from decimal import Decimal

from django.db.models import Count
from rest_framework import serializers

from .enums import CalculationType, TargetAmountSource
from .services import create_payroll_v2_run, generate_payroll_item_rule_name
from .models import (
    EmployeeCompensation,
    EmployeePayrollItem,
    PayrollCatalogItem,
    PayrollCatalogItemRule,
    PayrollEmployeeItem,
    PayrollLineItem,
    PayrollPayslipTemplate,
    PayrollPeriod,
    PaySchedule,
    PayrollRunRecord,
    PayrollSettings,
    PayrollTableView,
)


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
    employee_count = serializers.IntegerField(read_only=True, required=False)
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
    employee_items = PayrollEmployeeItemSerializer(many=True, read_only=True)
    columns = serializers.SerializerMethodField()
    rows = serializers.SerializerMethodField()
    table_view_snapshot = serializers.JSONField(read_only=True)
    payslip_template_snapshot = serializers.JSONField(read_only=True)
    totals = serializers.SerializerMethodField()

    class Meta(PayrollRunListSerializer.Meta):
        fields = PayrollRunListSerializer.Meta.fields + [
            "table_view",
            "table_view_snapshot",
            "payslip_template",
            "payslip_template_snapshot",
            "columns",
            "rows",
            "totals",
            "employee_items",
        ]

    def get_totals(self, obj):
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


class PayrollSettingsSerializer(serializers.ModelSerializer):
    transaction_type_name = serializers.CharField(
        source="transaction_type.name",
        read_only=True,
    )
    transaction_type_code = serializers.CharField(
        source="transaction_type.code",
        read_only=True,
    )

    class Meta:
        model = PayrollSettings
        fields = [
            "id",
            "transaction_type",
            "transaction_type_name",
            "transaction_type_code",
            "payslip_table_column_labels",
            "show_leave_on_paystub",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "transaction_type_name",
            "transaction_type_code",
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

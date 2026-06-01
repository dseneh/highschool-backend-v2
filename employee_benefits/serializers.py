from decimal import Decimal

from rest_framework import serializers

from payroll_v2.enums import CalculationType, TargetAmountSource
from payroll_v2.serializers import EmployeeDisplaySerializer

from .models import (
    BenefitRequest,
    BenefitRequestLine,
    BenefitSettings,
    BenefitType,
    BenefitTypeRule,
    EmployeeBenefit,
)
from .services import generate_benefit_request_number, generate_benefit_type_rule_name, validate_benefit_request_period


class BenefitTypeRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = BenefitTypeRule
        fields = [
            "id",
            "benefit_type",
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
        validated_data["name"] = generate_benefit_type_rule_name(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        snapshot = {
            "calculation_type": validated_data.get("calculation_type", instance.calculation_type),
            "value": validated_data.get("value", instance.value),
            "formula": validated_data.get("formula", instance.formula),
            "target_amount_source": validated_data.get(
                "target_amount_source", instance.target_amount_source
            ),
            "target_min_amount": validated_data.get("target_min_amount", instance.target_min_amount),
            "target_max_amount": validated_data.get("target_max_amount", instance.target_max_amount),
        }
        validated_data["name"] = generate_benefit_type_rule_name(snapshot)
        return super().update(instance, validated_data)


class BenefitTypeSerializer(serializers.ModelSerializer):
    rules = BenefitTypeRuleSerializer(many=True, read_only=True)
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = BenefitType
        fields = [
            "id",
            "name",
            "code",
            "description",
            "is_active",
            "rules",
            "employee_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_employee_count(self, obj):
        return getattr(obj, "employee_count", None) or obj.employee_assignments.filter(is_active=True).count()


class EmployeeBenefitSerializer(serializers.ModelSerializer):
    employee_display = EmployeeDisplaySerializer(source="employee", read_only=True)
    benefit_type_name = serializers.CharField(source="benefit_type.name", read_only=True)
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeBenefit
        fields = [
            "id",
            "employee",
            "employee_display",
            "benefit_type",
            "benefit_type_name",
            "display_name",
            "name_override",
            "calculation_type",
            "value",
            "formula",
            "target_amount_source",
            "calculation_limit",
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

    def get_display_name(self, obj):
        return obj.get_name()

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


class BenefitRequestLineSerializer(serializers.ModelSerializer):
    employee_display = EmployeeDisplaySerializer(source="employee", read_only=True)
    benefit_type_name = serializers.CharField(source="request.benefit_type.name", read_only=True)
    request_number = serializers.CharField(source="request.request_number", read_only=True)
    request_status = serializers.CharField(source="request.status", read_only=True)
    period_start = serializers.DateField(source="request.period_start", read_only=True)
    period_end = serializers.DateField(source="request.period_end", read_only=True)
    payment_date = serializers.DateField(source="request.payment_date", read_only=True)

    class Meta:
        model = BenefitRequestLine
        fields = [
            "id",
            "request",
            "request_number",
            "request_status",
            "benefit_type_name",
            "period_start",
            "period_end",
            "payment_date",
            "employee",
            "employee_display",
            "employee_benefit",
            "computed_amount",
            "final_amount",
            "amount_overridden",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["computed_amount", "created_at", "updated_at"]

    def update(self, instance, validated_data):
        if "final_amount" in validated_data:
            new_amount = validated_data["final_amount"]
            if new_amount != instance.computed_amount:
                validated_data["amount_overridden"] = True
            instance = super().update(instance, validated_data)
            instance.request.recalculate_totals()
            return instance
        return super().update(instance, validated_data)


class BenefitRequestListSerializer(serializers.ModelSerializer):
    benefit_type_name = serializers.CharField(source="benefit_type.name", read_only=True)
    currency_code = serializers.SerializerMethodField()
    line_count = serializers.SerializerMethodField()

    class Meta:
        model = BenefitRequest
        fields = [
            "id",
            "request_number",
            "benefit_type",
            "benefit_type_name",
            "period_start",
            "period_end",
            "payment_date",
            "status",
            "currency",
            "currency_code",
            "bank_account",
            "total_amount",
            "line_count",
            "approved_at",
            "paid_at",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "request_number",
            "total_amount",
            "approved_at",
            "paid_at",
            "created_at",
            "updated_at",
        ]

    def get_currency_code(self, obj):
        currency = getattr(obj, "currency", None)
        return getattr(currency, "code", None) if currency else None

    def get_line_count(self, obj):
        return getattr(obj, "line_count", None) or obj.lines.count()


class BenefitRequestDetailSerializer(BenefitRequestListSerializer):
    lines = serializers.SerializerMethodField()
    paid_table_snapshot = serializers.JSONField(read_only=True)
    approved_by_name = serializers.SerializerMethodField()

    class Meta(BenefitRequestListSerializer.Meta):
        fields = BenefitRequestListSerializer.Meta.fields + [
            "lines",
            "paid_table_snapshot",
            "approved_by",
            "approved_by_name",
        ]

    def _paid_snapshot(self, obj):
        from employee_benefits.enums import BenefitRequestStatus

        snapshot = getattr(obj, "paid_table_snapshot", None) or {}
        if not snapshot.get("rows"):
            return None
        if obj.status != BenefitRequestStatus.PAID:
            return None
        return snapshot

    def get_lines(self, obj):
        paid_snapshot = self._paid_snapshot(obj)
        if paid_snapshot is not None:
            return paid_snapshot.get("rows") or []
        return BenefitRequestLineSerializer(obj.lines.all(), many=True).data

    def get_approved_by_name(self, obj):
        user = getattr(obj, "approved_by", None)
        if not user:
            return None
        return getattr(user, "get_full_name", lambda: user.username)() or user.username


class BenefitRequestWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = BenefitRequest
        fields = [
            "id",
            "request_number",
            "benefit_type",
            "period_start",
            "period_end",
            "payment_date",
            "status",
            "currency",
            "bank_account",
            "notes",
        ]
        read_only_fields = ["request_number", "status"]

    def validate(self, attrs):
        benefit_type = attrs.get("benefit_type") or (self.instance.benefit_type if self.instance else None)
        period_start = attrs.get("period_start") or (self.instance.period_start if self.instance else None)
        period_end = attrs.get("period_end") or (self.instance.period_end if self.instance else None)
        if benefit_type and period_start and period_end:
            exclude_id = self.instance.id if self.instance else None
            validate_benefit_request_period(
                benefit_type=benefit_type,
                period_start=period_start,
                period_end=period_end,
                exclude_id=exclude_id,
            )
        return attrs

    def create(self, validated_data):
        validated_data["request_number"] = generate_benefit_request_number()
        return super().create(validated_data)


class GenerateBenefitRequestSerializer(serializers.Serializer):
    employee_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )


class SyncBenefitEmployeesSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=["all", "selected", "department", "position"])
    employee_ids = serializers.ListField(child=serializers.CharField(), required=False, allow_empty=True)
    department_id = serializers.UUIDField(required=False, allow_null=True)
    position_id = serializers.UUIDField(required=False, allow_null=True)


class BenefitSettingsSerializer(serializers.ModelSerializer):
    transaction_type_name = serializers.CharField(source="transaction_type.name", read_only=True)
    transaction_type_code = serializers.CharField(source="transaction_type.code", read_only=True)

    class Meta:
        model = BenefitSettings
        fields = [
            "id",
            "transaction_type",
            "transaction_type_name",
            "transaction_type_code",
            "max_period_days",
            "default_period_days",
            "min_days_between_requests",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        max_days = attrs.get(
            "max_period_days",
            self.instance.max_period_days if self.instance else 30,
        )
        default_days = attrs.get(
            "default_period_days",
            self.instance.default_period_days if self.instance else 30,
        )
        if default_days > max_days:
            raise serializers.ValidationError(
                {"default_period_days": "Default period cannot exceed the maximum period length."}
            )
        return attrs

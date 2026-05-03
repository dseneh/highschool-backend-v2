"""Payroll serializers."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import (
    EmployeeTaxRuleOverride,
    PayrollItem,
    PayrollItemType,
    PayrollPeriod,
    PayrollRun,
    Payslip,
    PaySchedule,
    TaxRule,
)


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


class PayScheduleSerializer(serializers.ModelSerializer):
    currency_code = serializers.CharField(source="currency.code", read_only=True)
    currency_symbol = serializers.CharField(source="currency.symbol", read_only=True)

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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.periods.exists():
            # Currency frozen once any period exists for the schedule.
            new_currency = attrs.get("currency", instance.currency)
            if new_currency != instance.currency:
                raise serializers.ValidationError(
                    {"currency": "Currency cannot change after periods exist on this schedule."}
                )
        return attrs


# ---------------------------------------------------------------------------
# Period
# ---------------------------------------------------------------------------


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

    def validate(self, attrs):
        start = attrs.get("start_date") or (self.instance and self.instance.start_date)
        end = attrs.get("end_date") or (self.instance and self.instance.end_date)
        payment = attrs.get("payment_date") or (self.instance and self.instance.payment_date)
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "End date must be on or after start date."})
        if end and payment and payment < end:
            raise serializers.ValidationError(
                {"payment_date": "Payment date must be on or after end date."}
            )
        return attrs


# ---------------------------------------------------------------------------
# Payslip
# ---------------------------------------------------------------------------


class PayslipSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_number = serializers.CharField(source="employee.employee_number", read_only=True)
    payroll_run_status = serializers.CharField(source="payroll_run.status", read_only=True)
    payroll_run_period_name = serializers.CharField(source="payroll_run.period.name", read_only=True)
    currency_code = serializers.CharField(source="currency.code", read_only=True)
    currency_symbol = serializers.CharField(source="currency.symbol", read_only=True)

    class Meta:
        model = Payslip
        fields = [
            "id",
            "payroll_run",
            "payroll_run_status",
            "payroll_run_period_name",
            "employee",
            "employee_name",
            "employee_number",
            "currency",
            "currency_code",
            "currency_symbol",
            "basic_salary",
            "overtime_hours",
            "overtime_pay",
            "unpaid_leave_days",
            "allowances",
            "deductions",
            "tax",
            "gross_pay",
            "net_pay",
            "breakdown",
            "generated_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "payroll_run",
            "employee",
            "currency",
            "currency_code",
            "currency_symbol",
            "employee_name",
            "employee_number",
            "basic_salary",
            "overtime_pay",
            "allowances",
            "deductions",
            "tax",
            "gross_pay",
            "net_pay",
            "breakdown",
            "generated_at",
            "created_at",
            "updated_at",
        ]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() if obj.employee else None


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class PayrollRunSerializer(serializers.ModelSerializer):
    period_name = serializers.CharField(source="period.name", read_only=True)
    schedule = serializers.PrimaryKeyRelatedField(source="period.schedule", read_only=True)
    schedule_name = serializers.CharField(source="period.schedule.name", read_only=True)
    currency_code = serializers.CharField(source="period.schedule.currency.code", read_only=True)
    currency_symbol = serializers.CharField(source="period.schedule.currency.symbol", read_only=True)
    period_start = serializers.DateField(source="period.start_date", read_only=True)
    period_end = serializers.DateField(source="period.end_date", read_only=True)
    payment_date = serializers.DateField(source="period.payment_date", read_only=True)

    employee_count = serializers.SerializerMethodField()
    totals = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = [
            "id",
            "period",
            "period_name",
            "schedule",
            "schedule_name",
            "currency_code",
            "currency_symbol",
            "period_start",
            "period_end",
            "payment_date",
            "status",
            "notes",
            "approved_at",
            "paid_at",
            "employee_count",
            "totals",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "approved_at",
            "paid_at",
            "created_at",
            "updated_at",
        ]

    def get_employee_count(self, obj):
        return obj.payslips.count()

    def get_totals(self, obj):
        from django.db.models import Sum

        agg = obj.payslips.aggregate(
            gross=Sum("gross_pay"),
            allowances=Sum("allowances"),
            deductions=Sum("deductions"),
            tax=Sum("tax"),
            net=Sum("net_pay"),
        )
        return {
            "gross": str(agg["gross"] or Decimal("0.00")),
            "allowances": str(agg["allowances"] or Decimal("0.00")),
            "deductions": str(agg["deductions"] or Decimal("0.00")),
            "tax": str(agg["tax"] or Decimal("0.00")),
            "net": str(agg["net"] or Decimal("0.00")),
        }


# ---------------------------------------------------------------------------
# PayrollItem
# ---------------------------------------------------------------------------


class PayrollItemTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollItemType
        fields = [
            "id",
            "name",
            "code",
            "item_type",
            "calculation_type",
            "default_value",
            "default_formula",
            "applies_to",
            "default_amount",
            "description",
            "is_active",
            "is_system_managed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_system_managed", "created_at", "updated_at"]

    def validate(self, attrs):
        if self.instance is not None and getattr(self.instance, "is_system_managed", False):
            locked_fields = {"name", "code", "item_type", "is_active"}
            for field in locked_fields:
                if field in attrs:
                    current_value = getattr(self.instance, field, None)
                    if attrs[field] != current_value:
                        raise serializers.ValidationError(
                            {field: "This field cannot be changed for system-managed payroll item types."}
                        )
        calc = attrs.get("calculation_type", getattr(self.instance, "calculation_type", None))
        if calc == PayrollItemType.CalculationType.FORMULA:
            formula = attrs.get("default_formula", getattr(self.instance, "default_formula", ""))
            if not (formula or "").strip():
                raise serializers.ValidationError(
                    {"default_formula": "Formula is required when calculation type is FORMULA."}
                )
        return super().validate(attrs)


class PayrollItemSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    item_type_ref_name = serializers.CharField(source="item_type_ref.name", read_only=True)
    item_type_ref_code = serializers.CharField(source="item_type_ref.code", read_only=True)

    class Meta:
        model = PayrollItem
        fields = [
            "id",
            "employee",
            "employee_name",
            "item_type_ref",
            "item_type_ref_name",
            "item_type_ref_code",
            "name",
            "item_type",
            "calculation_type",
            "value",
            "formula",
            "applies_to",
            "amount",
            "is_active",
            "effective_from",
            "effective_to",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "name", "item_type", "created_at", "updated_at"]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() if obj.employee else None

    def validate(self, attrs):
        item_type_ref = attrs.get("item_type_ref", getattr(self.instance, "item_type_ref", None))
        if item_type_ref is None:
            raise serializers.ValidationError(
                {"item_type_ref": "Catalog payroll item type is required."}
            )
        if not item_type_ref.is_active:
            raise serializers.ValidationError(
                {"item_type_ref": "This payroll item type is inactive."}
            )
        attrs["name"] = item_type_ref.name
        attrs["item_type"] = item_type_ref.item_type
        calc = attrs.get("calculation_type", getattr(self.instance, "calculation_type", None))
        if calc == PayrollItem.CalculationType.FORMULA:
            formula = attrs.get("formula", getattr(self.instance, "formula", ""))
            if not (formula or "").strip():
                raise serializers.ValidationError(
                    {"formula": "Formula is required when calculation type is FORMULA."}
                )
        return super().validate(attrs)


# ---------------------------------------------------------------------------
# TaxRule
# ---------------------------------------------------------------------------


class TaxRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRule
        fields = [
            "id",
            "name",
            "code",
            "description",
            "calculation_type",
            "value",
            "formula",
            "applies_to",
            "priority",
            "is_active",
            "effective_from",
            "effective_to",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        calc = attrs.get("calculation_type") or (self.instance and self.instance.calculation_type)
        formula = attrs.get("formula", self.instance.formula if self.instance else "")
        if calc == TaxRule.CalculationType.FORMULA and not (formula or "").strip():
            raise serializers.ValidationError(
                {"formula": "Formula is required when calculation type is 'formula'."}
            )
        return attrs


class EmployeeTaxRuleOverrideSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source="rule.name", read_only=True)
    rule_code = serializers.CharField(source="rule.code", read_only=True)
    rule_calculation_type = serializers.CharField(source="rule.calculation_type", read_only=True)
    rule_value = serializers.DecimalField(
        source="rule.value", max_digits=12, decimal_places=4, read_only=True
    )
    rule_formula = serializers.CharField(source="rule.formula", read_only=True)
    rule_applies_to = serializers.CharField(source="rule.applies_to", read_only=True)

    class Meta:
        model = EmployeeTaxRuleOverride
        fields = [
            "id",
            "employee",
            "rule",
            "rule_name",
            "rule_code",
            "rule_calculation_type",
            "rule_value",
            "rule_formula",
            "rule_applies_to",
            "calculation_type",
            "value",
            "formula",
            "applies_to",
            "is_active",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        calc = attrs.get(
            "calculation_type", getattr(self.instance, "calculation_type", None)
        )
        if calc == EmployeeTaxRuleOverride.CalculationType.FORMULA:
            formula = attrs.get("formula", getattr(self.instance, "formula", ""))
            if not (formula or "").strip():
                raise serializers.ValidationError(
                    {"formula": "Formula is required when calculation type is 'formula'."}
                )
        return attrs

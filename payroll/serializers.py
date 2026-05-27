"""Payroll serializers."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from accounting.models import AccountingBankAccount, AccountingTransactionType

from .models import (
    AmountCalculationType,
    EmployeeTaxRuleOverride,
    ItemAppliesTo,
    PayrollItem,
    PayrollItemType,
    PayrollItemTypeRule,
    PayrollPeriod,
    PayrollPayslipColumnGroup,
    PayrollRun,
    PayrollSettings,
    Payslip,
    PaySchedule,
    TaxAmountRule,
    TaxAppliesTo,
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
    id_number = serializers.CharField(source="employee.id_number", read_only=True)
    department_name = serializers.CharField(
        source="employee.department.name",
        read_only=True,
        allow_null=True,
    )
    position_title = serializers.CharField(
        source="employee.position.title",
        read_only=True,
        allow_null=True,
    )
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
            "id_number",
            "department_name",
            "position_title",
            "currency",
            "currency_code",
            "currency_symbol",
            "basic_salary",
            "overtime_hours",
            "overtime_pay",
            "unpaid_leave_days",
            "allowances",
            "adjustments",
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
            "id_number",
            "department_name",
            "position_title",
            "basic_salary",
            "overtime_pay",
            "allowances",
            "adjustments",
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


class PayrollPayslipColumnGroupSerializer(serializers.ModelSerializer):
    item_type_count = serializers.SerializerMethodField()

    class Meta:
        model = PayrollPayslipColumnGroup
        fields = [
            "id",
            "label",
            "sort_order",
            "item_type_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "item_type_count", "created_at", "updated_at"]

    def get_item_type_count(self, obj):
        return obj.item_types.count()


class PayrollRunSerializer(serializers.ModelSerializer):
    period_name = serializers.CharField(source="period.name", read_only=True)
    schedule = serializers.PrimaryKeyRelatedField(source="period.schedule", read_only=True)
    schedule_name = serializers.CharField(source="period.schedule.name", read_only=True)
    currency_code = serializers.CharField(source="period.schedule.currency.code", read_only=True)
    currency_symbol = serializers.CharField(source="period.schedule.currency.symbol", read_only=True)
    period_start = serializers.DateField(source="period.start_date", read_only=True)
    period_end = serializers.DateField(source="period.end_date", read_only=True)
    payment_date = serializers.DateField(source="period.payment_date", read_only=True)
    bank_account_name = serializers.CharField(source="bank_account.account_name", read_only=True)
    bank_account_number = serializers.CharField(source="bank_account.account_number", read_only=True)
    journal_reference = serializers.SerializerMethodField()
    posting_status = serializers.SerializerMethodField()

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
            "bank_account",
            "bank_account_name",
            "bank_account_number",
            "journal_reference",
            "posting_status",
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
            "bank_account_name",
            "bank_account_number",
            "journal_reference",
            "posting_status",
            "created_at",
            "updated_at",
        ]

    def validate_bank_account(self, value):
        if value is None:
            return value
        if value.status != AccountingBankAccount.AccountStatus.ACTIVE:
            raise serializers.ValidationError("Bank account must be active.")
        if value.ledger_account_id is None:
            raise serializers.ValidationError("Bank account must have a linked ledger account.")
        return value

    def validate(self, attrs):
        bank_account = attrs.get("bank_account")
        if bank_account is None and self.instance is not None:
            bank_account = self.instance.bank_account
        instance = self.instance
        if instance and instance.status == PayrollRun.Status.PAID:
            if attrs:
                raise serializers.ValidationError("Paid payroll runs cannot be edited.")
        if (
            instance
            and instance.status != PayrollRun.Status.DRAFT
            and "bank_account" in attrs
            and attrs.get("bank_account") != instance.bank_account
        ):
            raise serializers.ValidationError(
                {"bank_account": "Disbursement account can only be changed while the run is in draft."}
            )
        schedule_currency = None
        if instance is not None:
            schedule_currency = instance.period.schedule.currency
        elif attrs.get("period") is not None:
            schedule_currency = attrs["period"].schedule.currency
        if bank_account and schedule_currency and bank_account.currency_id != schedule_currency.id:
            raise serializers.ValidationError(
                {"bank_account": "Bank account currency must match the pay schedule currency."}
            )
        return attrs

    def get_journal_reference(self, obj):
        batch = (
            obj.accounting_posting_batches.filter(
                batch_status="posted",
            )
            .select_related("journal_entry")
            .order_by("-created_at")
            .first()
        )
        if batch and batch.journal_entry:
            return batch.journal_entry.reference_number
        return None

    def get_posting_status(self, obj):
        batch = obj.accounting_posting_batches.order_by("-created_at").first()
        return batch.batch_status if batch else None

    def get_employee_count(self, obj):
        return obj.payslips.count()

    def get_totals(self, obj):
        from django.db.models import Sum

        agg = obj.payslips.aggregate(
            basic_salary=Sum("basic_salary"),
            overtime_hours=Sum("overtime_hours"),
            overtime_pay=Sum("overtime_pay"),
            unpaid_leave_days=Sum("unpaid_leave_days"),
            gross=Sum("gross_pay"),
            allowances=Sum("allowances"),
            adjustments=Sum("adjustments"),
            deductions=Sum("deductions"),
            tax=Sum("tax"),
            net=Sum("net_pay"),
        )
        take_home = agg["net"] or Decimal("0.00")
        adjustments = agg["adjustments"] or Decimal("0.00")
        taxable_net = take_home - adjustments
        return {
            "basic_salary": str(agg["basic_salary"] or Decimal("0.00")),
            "overtime_hours": str(agg["overtime_hours"] or Decimal("0.00")),
            "overtime_pay": str(agg["overtime_pay"] or Decimal("0.00")),
            "unpaid_leave_days": str(agg["unpaid_leave_days"] or Decimal("0.00")),
            "gross": str(agg["gross"] or Decimal("0.00")),
            "allowances": str(agg["allowances"] or Decimal("0.00")),
            "adjustments": str(adjustments),
            "deductions": str(agg["deductions"] or Decimal("0.00")),
            "tax": str(agg["tax"] or Decimal("0.00")),
            "taxable_net": str(taxable_net),
            "net": str(take_home),
        }


# ---------------------------------------------------------------------------
# Amount rules (shared)
# ---------------------------------------------------------------------------


def _validate_amount_rule_payload(data: dict, *, applies_to_choices) -> dict:
    calc = data.get("calculation_type") or AmountCalculationType.FLAT
    data["calculation_type"] = calc
    if calc in (AmountCalculationType.FLAT, AmountCalculationType.PERCENTAGE):
        if data.get("value") is None:
            raise serializers.ValidationError({"value": "Value is required for flat/percentage rules."})
    if calc == AmountCalculationType.FORMULA:
        formula = (data.get("formula") or "").strip()
        if not formula:
            raise serializers.ValidationError({"formula": "Formula is required for formula rules."})
    applies_to = data.get("applies_to")
    if applies_to and applies_to not in dict(applies_to_choices):
        raise serializers.ValidationError({"applies_to": "Invalid applies_to value."})
    return data


class PayrollItemTypeRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollItemTypeRule
        fields = [
            "id",
            "calculation_type",
            "value",
            "formula",
            "applies_to",
            "target_salary_min",
            "target_salary_max",
            "target_salary_by",
            "salary_limit",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        from .models import ItemAppliesTo

        merged = {}
        if self.instance:
            for field in self.Meta.fields:
                if field in ("id", "created_at", "updated_at"):
                    continue
                merged[field] = getattr(self.instance, field, None)
        merged.update(attrs)
        _validate_amount_rule_payload(merged, applies_to_choices=ItemAppliesTo.choices)
        attrs["calculation_type"] = merged["calculation_type"]
        return attrs


class TaxAmountRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxAmountRule
        fields = [
            "id",
            "calculation_type",
            "value",
            "formula",
            "applies_to",
            "target_salary_min",
            "target_salary_max",
            "target_salary_by",
            "salary_limit",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        from .models import TaxAppliesTo

        merged = {}
        if self.instance:
            for field in self.Meta.fields:
                if field in ("id", "created_at", "updated_at"):
                    continue
                merged[field] = getattr(self.instance, field, None)
        merged.update(attrs)
        _validate_amount_rule_payload(merged, applies_to_choices=TaxAppliesTo.choices)
        attrs["calculation_type"] = merged["calculation_type"]
        return attrs


def _sync_nested_rules(parent, rules_data, *, rule_model, parent_field):
    if rules_data is None:
        return
    existing = {str(r.id): r for r in parent.amount_rules.all()}
    keep_ids: set[str] = set()
    user = getattr(parent, "_request_user", None)

    for idx, rule_data in enumerate(rules_data):
        rule_id = rule_data.get("id")
        payload = {k: v for k, v in rule_data.items() if k != "id"}
        payload.setdefault("sort_order", idx)
        if rule_id and str(rule_id) in existing:
            rule = existing[str(rule_id)]
            for key, value in payload.items():
                setattr(rule, key, value)
            if user:
                rule.updated_by = user
            rule.save()
            keep_ids.add(str(rule.id))
        else:
            create_kwargs = {parent_field: parent, **payload}
            if user:
                create_kwargs["created_by"] = user
                create_kwargs["updated_by"] = user
            created = rule_model.objects.create(**create_kwargs)
            keep_ids.add(str(created.id))

    for rule_id, rule in existing.items():
        if rule_id not in keep_ids:
            rule.delete()


# ---------------------------------------------------------------------------
# PayrollItemType
# ---------------------------------------------------------------------------


class PayrollItemTypeSerializer(serializers.ModelSerializer):
    amount_rules = PayrollItemTypeRuleSerializer(many=True, required=False)
    payslip_column_group = serializers.PrimaryKeyRelatedField(
        queryset=PayrollPayslipColumnGroup.objects.all(),
        allow_null=True,
        required=False,
    )
    payslip_column_group_label = serializers.CharField(
        source="payslip_column_group.label",
        read_only=True,
    )

    class Meta:
        model = PayrollItemType
        fields = [
            "id",
            "name",
            "code",
            "item_type",
            "is_taxable",
            "description",
            "is_active",
            "is_system_managed",
            "payslip_column_group",
            "payslip_column_group_label",
            "amount_rules",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_system_managed", "payslip_column_group_label", "created_at", "updated_at"]

    def validate(self, attrs):
        if self.instance is not None and getattr(self.instance, "is_system_managed", False):
            locked_fields = {"name", "code", "item_type", "is_taxable", "is_active"}
            for field in locked_fields:
                if field in attrs:
                    current_value = getattr(self.instance, field, None)
                    if attrs[field] != current_value:
                        raise serializers.ValidationError(
                            {field: "This field cannot be changed for system-managed payroll item types."}
                        )

        item_type = attrs.get("item_type", getattr(self.instance, "item_type", None))
        if item_type == PayrollItemType.ItemType.DEDUCTION:
            attrs["is_taxable"] = True
        elif item_type == PayrollItemType.ItemType.ADJUSTMENT:
            attrs["is_taxable"] = False
        elif "is_taxable" not in attrs and self.instance is None:
            attrs["is_taxable"] = True

        return super().validate(attrs)

    @transaction.atomic
    def create(self, validated_data):
        rules_data = validated_data.pop("amount_rules", [])
        instance = super().create(validated_data)
        instance._request_user = self.context["request"].user
        _sync_nested_rules(
            instance,
            rules_data,
            rule_model=PayrollItemTypeRule,
            parent_field="item_type",
        )
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        rules_data = validated_data.pop("amount_rules", None)
        instance = super().update(instance, validated_data)
        if rules_data is not None:
            instance._request_user = self.context["request"].user
            _sync_nested_rules(
                instance,
                rules_data,
                rule_model=PayrollItemTypeRule,
                parent_field="item_type",
            )
        return instance


# ---------------------------------------------------------------------------
# PayrollItem
# ---------------------------------------------------------------------------


class PayrollItemSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    item_type_ref_name = serializers.CharField(source="item_type_ref.name", read_only=True)
    item_type_ref_code = serializers.CharField(source="item_type_ref.code", read_only=True)
    has_amount_override = serializers.BooleanField(read_only=True)

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
            "is_active",
            "effective_from",
            "effective_to",
            "notes",
            "override_calculation_type",
            "override_value",
            "override_formula",
            "override_applies_to",
            "has_amount_override",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "name", "item_type", "has_amount_override", "created_at", "updated_at"]

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

        override_calc = attrs.get(
            "override_calculation_type",
            getattr(self.instance, "override_calculation_type", None),
        )
        if override_calc in ("", None):
            attrs["override_calculation_type"] = None
            attrs["override_value"] = None
            attrs["override_formula"] = ""
            attrs["override_applies_to"] = None
        else:
            if override_calc == AmountCalculationType.FORMULA:
                formula = attrs.get(
                    "override_formula",
                    getattr(self.instance, "override_formula", ""),
                )
                if not (formula or "").strip():
                    raise serializers.ValidationError(
                        {"override_formula": "Formula is required when calculation type is 'formula'."}
                    )
            elif override_calc in (AmountCalculationType.FLAT, AmountCalculationType.PERCENTAGE):
                if attrs.get("override_value", getattr(self.instance, "override_value", None)) is None:
                    raise serializers.ValidationError(
                        {"override_value": "Value is required for flat or percentage overrides."}
                    )
            if not attrs.get(
                "override_applies_to",
                getattr(self.instance, "override_applies_to", None),
            ):
                attrs["override_applies_to"] = ItemAppliesTo.BASIC

        return super().validate(attrs)


# ---------------------------------------------------------------------------
# TaxRule
# ---------------------------------------------------------------------------


class TaxRuleSerializer(serializers.ModelSerializer):
    amount_rules = TaxAmountRuleSerializer(many=True, required=False)

    class Meta:
        model = TaxRule
        fields = [
            "id",
            "name",
            "code",
            "description",
            "priority",
            "is_active",
            "effective_from",
            "effective_to",
            "amount_rules",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    @transaction.atomic
    def create(self, validated_data):
        rules_data = validated_data.pop("amount_rules", [])
        instance = super().create(validated_data)
        instance._request_user = self.context["request"].user
        _sync_nested_rules(
            instance,
            rules_data,
            rule_model=TaxAmountRule,
            parent_field="tax_rule",
        )
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        rules_data = validated_data.pop("amount_rules", None)
        instance = super().update(instance, validated_data)
        if rules_data is not None:
            instance._request_user = self.context["request"].user
            _sync_nested_rules(
                instance,
                rules_data,
                rule_model=TaxAmountRule,
                parent_field="tax_rule",
            )
        return instance


class EmployeeTaxRuleOverrideSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source="rule.name", read_only=True)
    rule_code = serializers.CharField(source="rule.code", read_only=True)

    class Meta:
        model = EmployeeTaxRuleOverride
        fields = [
            "id",
            "employee",
            "rule",
            "rule_name",
            "rule_code",
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
        applies_to = attrs.get("applies_to", getattr(self.instance, "applies_to", None))
        if applies_to and applies_to not in dict(TaxAppliesTo.choices):
            raise serializers.ValidationError({"applies_to": "Invalid applies_to value."})
        return attrs


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


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

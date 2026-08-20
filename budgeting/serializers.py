from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Max
from rest_framework import serializers

from .models import (
    Budget, BudgetEnrollmentAssumption, BudgetLifecycleEvent, BudgetLine,
    BudgetLinePeriod, BudgetRevision, BudgetRevisionLineDelta, BudgetSection,
)


class CleanModelSerializer(serializers.ModelSerializer):
    def _clean(self, instance):
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)

    def create(self, validated_data):
        instance = self.Meta.model(**validated_data)
        self._clean(instance)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        for key, value in validated_data.items():
            setattr(instance, key, value)
        self._clean(instance)
        instance.save()
        return instance


class BudgetLinePeriodSerializer(CleanModelSerializer):
    class Meta:
        model = BudgetLinePeriod
        fields = "__all__"
        read_only_fields = ["created_by", "updated_by"]


class BudgetLineSerializer(CleanModelSerializer):
    periods = BudgetLinePeriodSerializer(many=True, read_only=True)
    effective_planned_amount = serializers.SerializerMethodField()

    def get_effective_planned_amount(self, obj):
        approved_delta = getattr(obj, "approved_delta", None)
        if approved_delta is None:
            approved_delta = sum(
                (
                    delta.amount_delta
                    for delta in obj.revision_deltas.all()
                    if delta.revision.status == BudgetRevision.Status.APPROVED
                ),
                0,
            )
        return obj.annual_planned_amount + approved_delta

    class Meta:
        model = BudgetLine
        fields = "__all__"
        read_only_fields = ["created_by", "updated_by"]


class BudgetSectionSerializer(CleanModelSerializer):
    lines = BudgetLineSerializer(many=True, read_only=True)

    class Meta:
        model = BudgetSection
        fields = "__all__"
        read_only_fields = ["created_by", "updated_by"]


class BudgetEnrollmentAssumptionSerializer(CleanModelSerializer):
    class Meta:
        model = BudgetEnrollmentAssumption
        fields = "__all__"
        read_only_fields = ["created_by", "updated_by"]


class BudgetRevisionLineDeltaSerializer(CleanModelSerializer):
    class Meta:
        model = BudgetRevisionLineDelta
        fields = "__all__"
        read_only_fields = ["created_by", "updated_by"]


class BudgetRevisionSerializer(CleanModelSerializer):
    line_deltas = BudgetRevisionLineDeltaSerializer(many=True, read_only=True)

    def create(self, validated_data):
        Budget.objects.select_for_update().get(pk=validated_data["budget"].pk)
        if not validated_data.get("number"):
            maximum = BudgetRevision.objects.filter(budget=validated_data["budget"]).aggregate(Max("number"))["number__max"] or 0
            validated_data["number"] = maximum + 1
        return super().create(validated_data)

    class Meta:
        model = BudgetRevision
        fields = "__all__"
        read_only_fields = ["status", "approved_at", "approved_by", "created_by", "updated_by"]
        extra_kwargs = {"number": {"required": False}}


class BudgetLifecycleEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = BudgetLifecycleEvent
        fields = "__all__"


class BudgetSerializer(CleanModelSerializer):
    sections = BudgetSectionSerializer(many=True, read_only=True)
    enrollment_assumptions = BudgetEnrollmentAssumptionSerializer(many=True, read_only=True)
    revisions = BudgetRevisionSerializer(many=True, read_only=True)
    lifecycle_events = BudgetLifecycleEventSerializer(many=True, read_only=True)

    class Meta:
        model = Budget
        fields = "__all__"
        read_only_fields = [
            "status", "is_original", "version", "submitted_at", "submitted_by",
            "approved_at", "approved_by", "activated_at", "activated_by",
            "closed_at", "closed_by", "created_by", "updated_by",
        ]

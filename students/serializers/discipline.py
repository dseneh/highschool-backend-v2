from django.utils import timezone
from rest_framework import serializers

from ..models import DisciplinaryActionType, StudentDisciplinaryAction


class DisciplinaryActionTypeSerializer(serializers.ModelSerializer):
    DURATION_REQUIRED_OUTCOMES = {
        DisciplinaryActionType.ActionOutcome.DETENTION,
        DisciplinaryActionType.ActionOutcome.SUSPENSION,
        DisciplinaryActionType.ActionOutcome.EXPULSION,
        DisciplinaryActionType.ActionOutcome.PROBATION,
    }

    class Meta:
        model = DisciplinaryActionType
        fields = [
            "id",
            "name",
            "code",
            "category",
            "action_outcome",
            "description",
            "requires_start_date",
            "requires_end_date",
            "requires_parent_notification",
            "requires_approval",
            "default_duration_days",
            "max_duration_days",
            "default_severity",
            "allow_manual_override",
            "active",
        ]

    def validate(self, attrs):
        action_outcome = attrs.get("action_outcome")
        default_duration_days = attrs.get("default_duration_days")
        max_duration_days = attrs.get("max_duration_days")
        default_severity = attrs.get("default_severity")

        if self.instance:
            action_outcome = (
                action_outcome
                if action_outcome is not None
                else self.instance.action_outcome
            )
            default_duration_days = (
                default_duration_days
                if default_duration_days is not None
                else self.instance.default_duration_days
            )
            max_duration_days = (
                max_duration_days
                if max_duration_days is not None
                else self.instance.max_duration_days
            )
            default_severity = (
                default_severity
                if default_severity is not None
                else self.instance.default_severity
            )

        if default_duration_days is not None and default_duration_days < 1:
            raise serializers.ValidationError(
                {"default_duration_days": "Default days must be at least 1."}
            )

        if max_duration_days is not None and max_duration_days < 1:
            raise serializers.ValidationError(
                {"max_duration_days": "Max days must be at least 1."}
            )

        if (
            default_duration_days is not None
            and max_duration_days is not None
            and max_duration_days < default_duration_days
        ):
            raise serializers.ValidationError(
                {"max_duration_days": "Max days must be greater than or equal to default days."}
            )

        if action_outcome and action_outcome not in self.DURATION_REQUIRED_OUTCOMES:
            if default_duration_days not in (None, 1) or max_duration_days not in (None, 1):
                raise serializers.ValidationError(
                    {
                        "default_duration_days": (
                            "This action outcome does not use duration. Keep default and max days as 1."
                        )
                    }
                )

        if default_severity is not None and (default_severity < 1 or default_severity > 5):
            raise serializers.ValidationError(
                {"default_severity": "Default severity must be between 1 and 5."}
            )

        return attrs


class StudentDisciplinaryActionSerializer(serializers.ModelSerializer):
    student_id_number = serializers.CharField(source="student.id_number", read_only=True)
    student_full_name = serializers.CharField(source="student.get_full_name", read_only=True)
    is_active_window = serializers.SerializerMethodField()
    action_type_detail = DisciplinaryActionTypeSerializer(source="action_type", read_only=True)

    class Meta:
        model = StudentDisciplinaryAction
        fields = [
            "id",
            "student",
            "student_id_number",
            "student_full_name",
            "action_type",
            "action_type_detail",
            "title",
            "description",
            "action_taken",
            "start_date",
            "end_date",
            "duration_days",
            "severity",
            "status",
            "active",
            "is_active_window",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "student_id_number",
            "student_full_name",
            "is_active_window",
            "action_type_detail",
            "created_at",
            "updated_at",
        ]

    def get_is_active_window(self, obj):
        return obj.is_active_window

    def validate(self, attrs):
        action_type = attrs.get("action_type")
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")
        duration_days = attrs.get("duration_days")

        if self.instance:
            action_type = action_type or self.instance.action_type
            start_date = start_date or self.instance.start_date
            end_date = end_date or self.instance.end_date
            duration_days = duration_days or self.instance.duration_days

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "End date cannot be earlier than start date."}
            )

        if duration_days is not None and duration_days < 1:
            raise serializers.ValidationError(
                {"duration_days": "Duration days must be at least 1."}
            )

        if action_type:
            if action_type.requires_start_date and not start_date:
                raise serializers.ValidationError(
                    {"start_date": "Start date is required for this action type."}
                )
            if action_type.requires_end_date and not end_date and not duration_days:
                raise serializers.ValidationError(
                    {
                        "end_date": (
                            "End date or duration days is required for this action type."
                        )
                    }
                )

            if start_date and end_date and action_type.max_duration_days:
                resolved_days = (end_date - start_date).days + 1
                if resolved_days > action_type.max_duration_days:
                    raise serializers.ValidationError(
                        {
                            "end_date": (
                                f"This action allows at most {action_type.max_duration_days} days."
                            )
                        }
                    )

            if (
                action_type.action_outcome not in DisciplinaryActionTypeSerializer.DURATION_REQUIRED_OUTCOMES
                and start_date
                and end_date
            ):
                resolved_days = (end_date - start_date).days + 1
                if resolved_days > 1:
                    raise serializers.ValidationError(
                        {
                            "end_date": "This discipline outcome should be recorded as a single-day action."
                        }
                    )

        return attrs


class ActiveStudentDisciplinaryActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentDisciplinaryAction
        fields = [
            "id",
            "action_type",
            "title",
            "action_taken",
            "start_date",
            "end_date",
            "duration_days",
            "severity",
            "status",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["is_active_window"] = instance.is_active_window
        response["days_remaining"] = (instance.end_date - timezone.localdate()).days
        return response

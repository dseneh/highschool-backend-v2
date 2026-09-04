from django.utils import timezone
from rest_framework import serializers

from .enums import ApplicationStatus, ApplicationType
from .models import AdmissionApplication, AdmissionCycle, ApplicationPlacement, ApplicationStatusHistory


class PublicAdmissionCycleSerializer(serializers.ModelSerializer):
    eligible_grade_levels = serializers.SerializerMethodField()

    def get_eligible_grade_levels(self, obj):
        return [{"id": item.id, "name": item.name, "level": item.level} for item in obj.eligible_grade_levels.all()]

    class Meta:
        model = AdmissionCycle
        fields = ["id", "name", "academic_year", "opens_at", "closes_at", "new_admissions_open", "returning_registration_open", "instructions", "eligible_grade_levels"]


class AdmissionCycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdmissionCycle
        fields = "__all__"
        read_only_fields = ["created_by", "updated_by"]

    def validate(self, attrs):
        opens_at = attrs.get("opens_at", getattr(self.instance, "opens_at", None))
        closes_at = attrs.get("closes_at", getattr(self.instance, "closes_at", None))
        if opens_at and closes_at and closes_at <= opens_at:
            raise serializers.ValidationError({"closes_at": "Closing time must be after opening time."})
        return attrs


class PublicApplicationStartSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdmissionApplication
        fields = ["cycle", "application_type", "applicant_name", "applicant_email", "applicant_phone", "requested_grade_level"]

    def validate(self, attrs):
        cycle = attrs["cycle"]
        now = timezone.now()
        if not cycle.active or not (cycle.opens_at <= now <= cycle.closes_at):
            raise serializers.ValidationError({"cycle": "This admission cycle is not open."})
        application_type = attrs["application_type"]
        if application_type == ApplicationType.NEW_ADMISSION and not cycle.new_admissions_open:
            raise serializers.ValidationError({"application_type": "New admissions are closed."})
        if application_type == ApplicationType.RETURNING_REGISTRATION:
            raise serializers.ValidationError({
                "application_type": "Returning registration must begin through the verified student access flow."
            })
        if not attrs.get("applicant_email") and not attrs.get("applicant_phone"):
            raise serializers.ValidationError("Email or phone is required.")
        return attrs


class ApplicationPlacementSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationPlacement
        fields = ["id", "academic_year", "grade_level", "section", "enrolled_as", "notes"]


class ApplicationStatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationStatusHistory
        fields = ["id", "from_status", "to_status", "reason", "metadata", "created_at", "created_by"]


class AdmissionApplicationSerializer(serializers.ModelSerializer):
    placement = ApplicationPlacementSerializer(read_only=True)
    status_history = ApplicationStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = AdmissionApplication
        fields = [
            "id", "request_id", "application_type", "cycle", "status",
            "applicant_name", "applicant_email", "applicant_phone", "returning_student",
            "requested_grade_level", "assigned_reviewer", "student_profile",
            "guardian_profiles", "previous_school_records", "proposed_student_changes",
            "consents", "submitted_at", "decision_at", "version", "placement",
            "status_history", "created_at", "updated_at",
        ]
        read_only_fields = ["request_id", "status", "submitted_at", "decision_at", "version"]


class ApplicationTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ApplicationStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    version = serializers.IntegerField(min_value=1)

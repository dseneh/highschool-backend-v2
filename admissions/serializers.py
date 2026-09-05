from django.utils import timezone
from rest_framework import serializers

from academics.models import GradeLevel

from .enums import ApplicationStatus, ApplicationType
from .models import (
    AdmissionApplication, AdmissionCycle, ApplicationDocument,
    ApplicationDocumentRequirement, ApplicationInformationRequest,
    ApplicationMessage, ApplicationPlacement, ApplicationStatusHistory,
    ApplicationConversion,
)


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
        if not attrs.get("applicant_email"):
            raise serializers.ValidationError({"applicant_email": "Email is required for verification."})
        grade_level = attrs.get("requested_grade_level")
        eligible = cycle.eligible_grade_levels.all()
        if eligible.exists() and grade_level is None:
            raise serializers.ValidationError({"requested_grade_level": "Requested grade is required."})
        if grade_level is not None and eligible.exists() and not eligible.filter(pk=grade_level.pk).exists():
            raise serializers.ValidationError({"requested_grade_level": "This grade is not open for applications."})
        return attrs


class ApplicantVerificationSerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField(required=False)
    request_id = serializers.CharField(required=False, max_length=32)
    code = serializers.RegexField(r"^\d{6}$")

    def validate(self, attrs):
        if bool(attrs.get("challenge_id")) == bool(attrs.get("request_id")):
            raise serializers.ValidationError("Provide exactly one verification reference.")
        return attrs


class ApplicantAccessRequestSerializer(serializers.Serializer):
    request_id = serializers.CharField(max_length=32)
    email = serializers.EmailField()


class ReturningApplicationStartSerializer(serializers.Serializer):
    cycle = serializers.PrimaryKeyRelatedField(queryset=AdmissionCycle.objects.all())
    student_id = serializers.UUIDField(required=False)
    requested_grade_level = serializers.PrimaryKeyRelatedField(
        queryset=GradeLevel.objects.all()
    )

    def validate(self, attrs):
        cycle = attrs["cycle"]
        now = timezone.now()
        if not cycle.active or not (cycle.opens_at <= now <= cycle.closes_at):
            raise serializers.ValidationError({"cycle": "This admission cycle is not open."})
        if not cycle.returning_registration_open:
            raise serializers.ValidationError({"cycle": "Returning registration is closed."})
        grade_level = attrs["requested_grade_level"]
        eligible = cycle.eligible_grade_levels.all()
        if eligible.exists() and not eligible.filter(pk=grade_level.pk).exists():
            raise serializers.ValidationError({"requested_grade_level": "This grade is not open for registration."})
        return attrs


class PortalApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdmissionApplication
        fields = [
            "request_id", "application_type", "cycle", "status", "applicant_name",
            "applicant_email", "applicant_phone", "requested_grade_level",
            "student_profile", "guardian_profiles", "previous_school_records",
            "proposed_student_changes", "consents", "submitted_at", "decision_at",
            "version", "created_at", "updated_at",
        ]
        read_only_fields = [
            "request_id", "application_type", "cycle", "status", "applicant_email",
            "submitted_at", "decision_at", "version", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        if self.instance and self.instance.status != ApplicationStatus.DRAFT:
            raise serializers.ValidationError("Only draft applications can be edited.")
        return attrs


class ApplicationMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationMessage
        fields = ["id", "author_type", "body", "applicant_read_at", "school_read_at", "created_at"]
        read_only_fields = ["id", "author_type", "applicant_read_at", "school_read_at", "created_at"]

    def validate_body(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Message cannot be empty.")
        if len(value) > 5000:
            raise serializers.ValidationError("Message cannot exceed 5,000 characters.")
        return value


class InformationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationInformationRequest
        fields = ["id", "title", "instructions", "due_at", "status", "resolved_at", "created_at"]
        read_only_fields = fields


class InformationRequestCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationInformationRequest
        fields = ["title", "instructions", "due_at"]


class DocumentReviewSerializer(serializers.Serializer):
    review_status = serializers.ChoiceField(choices=ApplicationDocument.ReviewStatus.choices)
    review_note = serializers.CharField(required=False, allow_blank=True, default="")


class ApplicationDocumentSerializer(serializers.ModelSerializer):
    requirement_name = serializers.CharField(source="requirement.name", read_only=True)

    class Meta:
        model = ApplicationDocument
        fields = [
            "id", "requirement", "requirement_name", "original_name", "mime_type",
            "size_bytes", "checksum_sha256", "scan_status", "scan_completed_at", "review_status",
            "review_note", "created_at",
        ]
        read_only_fields = fields


class ApplicationDocumentRequirementSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationDocumentRequirement
        fields = [
            "id",
            "name",
            "instructions",
            "required",
            "allowed_extensions",
            "max_size_bytes",
        ]
        read_only_fields = fields


class ApplicationDocumentUploadSerializer(serializers.Serializer):
    requirement = serializers.PrimaryKeyRelatedField(queryset=ApplicationDocumentRequirement.objects.all())
    file = serializers.FileField()

    def validate(self, attrs):
        application = self.context["application"]
        requirement = attrs["requirement"]
        upload = attrs["file"]
        if requirement.cycle_id != application.cycle_id or requirement.application_type != application.application_type:
            raise serializers.ValidationError({"requirement": "This requirement does not apply to the application."})
        if requirement.grade_level_id and requirement.grade_level_id != application.requested_grade_level_id:
            raise serializers.ValidationError({"requirement": "This requirement does not apply to the requested grade."})
        if upload.size > requirement.max_size_bytes:
            raise serializers.ValidationError({"file": "The file exceeds the allowed size."})
        extension = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
        allowed = requirement.allowed_extensions or ["pdf", "png", "jpg", "jpeg"]
        if extension not in allowed:
            raise serializers.ValidationError({"file": "This file type is not allowed."})
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


class ApplicationConversionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationConversion
        fields = [
            "id", "status", "student", "enrollment", "accounting_bill",
            "error_code", "error_detail", "completed_at",
        ]
        read_only_fields = fields

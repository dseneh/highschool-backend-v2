from django.db import models
from rest_framework import serializers

from academics.models import AcademicYear, GradeLevel, MarkingPeriod, Subject

from ..models.historical_grade import HistoricalGradeRecord
from ..services.student_status import resolve_current_enrollment


def _student_current_grade_level_number(student) -> int | None:
    enrollment = resolve_current_enrollment(student)
    if enrollment and enrollment.grade_level_id:
        return enrollment.grade_level.level
    if student.grade_level_id:
        return student.grade_level.level
    return None


class UuidOrNameRelatedField(serializers.Field):
    default_error_messages = {
        "required": "This field is required.",
        "does_not_exist": "{model} does not exist.",
    }

    def __init__(self, queryset, **kwargs):
        self.queryset = queryset
        self.model = queryset.model
        self.allow_null = kwargs.get("allow_null", False)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if isinstance(data, models.Model):
            return data
        if isinstance(data, dict):
            data = data.get("id") or data.get("pk") or data.get("name")
        if data in (None, ""):
            if self.allow_null:
                return None
            self.fail("required")
        value = str(data).strip()
        obj = self.queryset.filter(id=value).first()
        if obj is None and hasattr(self.model, "name"):
            obj = self.queryset.filter(name__iexact=value).first()
        if obj is None:
            raise serializers.ValidationError(
                self.error_messages["does_not_exist"].format(
                    model=self.model._meta.verbose_name.title()
                )
            )
        return obj

    def to_representation(self, value):
        if value is None:
            return None
        return {"id": str(value.id), "name": getattr(value, "name", str(value))}


class HistoricalGradeRecordSerializer(serializers.ModelSerializer):
    source = serializers.ReadOnlyField(default="transferred")
    include_in_calculations = serializers.SerializerMethodField()
    counts_toward_year = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()
    grade_level = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()
    marking_period = serializers.SerializerMethodField()

    class Meta:
        model = HistoricalGradeRecord
        fields = [
            "id",
            "student",
            "institution_name",
            "academic_year",
            "academic_year_label",
            "period_start_date",
            "period_end_date",
            "grade_level",
            "subject_name",
            "subject",
            "marking_period",
            "final_percentage",
            "final_letter",
            "credits",
            "include_in_rankings",
            "include_in_honor_roll",
            "include_in_calculations",
            "counts_toward_year",
            "notes",
            "status",
            "verified_by",
            "verified_at",
            "source",
            "meta",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "student",
            "source",
            "verified_by",
            "verified_at",
            "created_at",
            "updated_at",
        ]

    def _fk(self, obj, attr):
        related = getattr(obj, attr, None)
        if not related:
            return None
        return {"id": str(related.id), "name": getattr(related, "name", str(related))}

    def get_academic_year(self, obj):
        ay = obj.academic_year
        if not ay:
            return None
        return {
            "id": str(ay.id),
            "name": ay.name,
            "year_type": ay.year_type,
        }

    def get_grade_level(self, obj):
        return self._fk(obj, "grade_level")

    def get_subject(self, obj):
        sub = obj.subject
        if not sub:
            return None
        return {"id": str(sub.id), "name": sub.name, "code": getattr(sub, "code", None)}

    def get_marking_period(self, obj):
        return self._fk(obj, "marking_period")

    def get_include_in_calculations(self, obj):
        return obj.include_in_calculations

    def get_counts_toward_year(self, obj):
        return obj.counts_toward_year


class HistoricalGradeRecordWriteSerializer(serializers.ModelSerializer):
    academic_year = UuidOrNameRelatedField(
        queryset=AcademicYear.objects.all(),
        required=False,
        allow_null=True,
    )
    grade_level = UuidOrNameRelatedField(queryset=GradeLevel.objects.all())
    subject = UuidOrNameRelatedField(queryset=Subject.objects.all())
    marking_period = UuidOrNameRelatedField(
        queryset=MarkingPeriod.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = HistoricalGradeRecord
        fields = [
            "institution_name",
            "academic_year",
            "academic_year_label",
            "period_start_date",
            "period_end_date",
            "grade_level",
            "subject_name",
            "subject",
            "marking_period",
            "final_percentage",
            "final_letter",
            "credits",
            "include_in_rankings",
            "include_in_honor_roll",
            "notes",
        ]

    def validate(self, attrs):
        student = self.context.get("student")
        grade_level = attrs.get("grade_level")
        if grade_level is None and self.instance is not None:
            grade_level = self.instance.grade_level

        if student and grade_level:
            current_level = _student_current_grade_level_number(student)
            if current_level is not None and grade_level.level >= current_level:
                raise serializers.ValidationError(
                    {
                        "grade_level": (
                            "Prior transcript grade level must be below the student's "
                            f"current grade level (level {current_level})."
                        )
                    }
                )

        academic_year = attrs.get("academic_year")
        if academic_year is None and self.instance is not None:
            academic_year = self.instance.academic_year
        academic_year_label = (attrs.get("academic_year_label") or "").strip()
        if academic_year and not academic_year_label:
            attrs["academic_year_label"] = academic_year.name or ""
        elif not academic_year_label and self.instance is not None:
            attrs["academic_year_label"] = self.instance.academic_year_label

        if not attrs.get("academic_year_label"):
            raise serializers.ValidationError(
                {"academic_year_label": "Academic year label is required."}
            )

        period_end_date = attrs.get("period_end_date")
        if period_end_date is None and self.instance is not None:
            period_end_date = self.instance.period_end_date
        if period_end_date is None:
            raise serializers.ValidationError(
                {"period_end_date": "End date is required for historical grade records."}
            )

        period_start_date = attrs.get("period_start_date")
        if period_start_date is None and self.instance is not None:
            period_start_date = self.instance.period_start_date
        if period_start_date and period_end_date and period_start_date > period_end_date:
            raise serializers.ValidationError(
                {"period_start_date": "Start date must be on or before the end date."}
            )

        subject = attrs.get("subject")
        if subject is None and self.instance is not None:
            subject = self.instance.subject

        if student and academic_year and subject:
            duplicate_qs = HistoricalGradeRecord.objects.filter(
                student=student,
                academic_year=academic_year,
                subject=subject,
            )
            if self.instance is not None:
                duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)
            if duplicate_qs.exists():
                raise serializers.ValidationError(
                    {
                        "subject": (
                            "This subject already has a grade for this academic year."
                        )
                    }
                )

        return attrs

    def create(self, validated_data):
        student = self.context["student"]
        validated_data["student"] = student
        return HistoricalGradeRecord.objects.create(**validated_data)


class HistoricalGradeStudentSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    id_number = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    photo = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    grade_level = serializers.DictField(allow_null=True)
    section = serializers.DictField(allow_null=True)
    record_count = serializers.IntegerField()
    verified_count = serializers.IntegerField()
    draft_count = serializers.IntegerField()
    institution_count = serializers.IntegerField()
    institutions = serializers.ListField(child=serializers.CharField())
    last_updated = serializers.DateTimeField(allow_null=True)
    verification_status = serializers.CharField()

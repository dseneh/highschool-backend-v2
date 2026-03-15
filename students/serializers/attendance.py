from rest_framework import serializers

from academics.models import MarkingPeriod

from ..models import Attendance
from common.status import AttendanceStatus


class AttendanceSerializer(serializers.ModelSerializer):
    marking_period = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        fields = [
            "id",
            "enrollment",
            "marking_period",
            "date",
            "status",
            "notes",
            "meta",
        ]

    def get_marking_period(self, instance):
        matching_marking_period = (
            MarkingPeriod.objects.filter(
                start_date__lte=instance.date,
                end_date__gte=instance.date,
                semester__academic_year=instance.enrollment.academic_year,
            )
            .order_by("start_date")
            .first()
        )
        return matching_marking_period.name if matching_marking_period else None

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["student"] = instance.enrollment.student.id_number
        response["student_name"] = instance.enrollment.student.get_full_name()
        return response


class AttendanceRosterEntrySerializer(serializers.Serializer):
    attendance_id = serializers.UUIDField(required=False, allow_null=True)
    enrollment_id = serializers.UUIDField()
    student_id = serializers.CharField()
    student_name = serializers.CharField()
    section_name = serializers.CharField()
    status = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class AttendanceSectionRosterSerializer(serializers.Serializer):
    section = serializers.DictField()
    marking_period = serializers.DictField(allow_null=True)
    date = serializers.DateField()
    summary = serializers.DictField()
    entries = AttendanceRosterEntrySerializer(many=True)


class AttendanceBulkEntryWriteSerializer(serializers.Serializer):
    enrollment_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=AttendanceStatus.choices())
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class AttendanceBulkUpsertSerializer(serializers.Serializer):
    date = serializers.DateField()
    entries = AttendanceBulkEntryWriteSerializer(many=True)

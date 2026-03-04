from rest_framework import serializers

from ..models import Attendance


class AttendanceSerializer(serializers.ModelSerializer):
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

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["student"] = instance.enrollment.student.id_number
        response["student_name"] = instance.enrollment.student.get_full_name()
        response["marking_period"] = instance.marking_period.name
        return response

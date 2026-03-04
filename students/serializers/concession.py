from rest_framework import serializers

from students.models import StudentConcession


class StudentConcessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentConcession
        fields = [
            "id",
            "student",
            "academic_year",
            "concession_type",
            "target",
            "value",
            "amount",
            "notes",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "amount", "created_at", "updated_at", "student"]

    def validate(self, attrs):
        concession_type = attrs.get("concession_type", getattr(self.instance, "concession_type", None))
        value = attrs.get("value", getattr(self.instance, "value", None))

        if concession_type == StudentConcession.TYPE_PERCENTAGE and value is not None:
            if value <= 0 or value > 100:
                raise serializers.ValidationError(
                    {"value": "Percentage concession value must be between 0 and 100."}
                )

        if concession_type == StudentConcession.TYPE_FLAT and value is not None and value <= 0:
            raise serializers.ValidationError(
                {"value": "Flat concession value must be greater than 0."}
            )

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["student"] = {
            "id": str(instance.student.id),
            "id_number": instance.student.id_number,
            "full_name": instance.student.get_full_name(),
        }
        data["academic_year"] = {
            "id": str(instance.academic_year.id),
            "name": instance.academic_year.name,
            "current": instance.academic_year.current,
        }
        return data

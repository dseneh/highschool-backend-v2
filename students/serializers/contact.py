from rest_framework import serializers

from ..models import StudentContact


class StudentContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentContact
        fields = [
            "id",
            "student",
            "first_name",
            "last_name",
            "relationship",
            "phone_number",
            "email",
            "address",
            "is_emergency",
            "is_primary",
            "photo",
            "notes",
            "meta",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["full_name"] = instance.full_name
        response["student"] = instance.student.id_number
        response["photo"] = instance.photo or instance.default_photo
        return response

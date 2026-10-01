from common.update_utils import ChangedFieldsModelSerializerMixin, PartialUpdateModelSerializer

from rest_framework import serializers


from ..models import StudentGuardian


class StudentGuardianSerializer(ChangedFieldsModelSerializerMixin, PartialUpdateModelSerializer):
    class Meta:
        read_only_fields = ["give_access", "portal_state", "portal_verified_at", "parent_profile_id"]
        model = StudentGuardian
        fields = [
            "give_access", "gender", "date_of_birth",
            "parent_profile_id",
            "portal_state",
            "portal_verified_at",
            "id",
            "id_number",
            "student",
            "first_name",
            "middle_name",
            "last_name",
            "relationship",
            "phone_number",
            "email",
            "address",
            "occupation",
            "workplace",
            "is_primary",
            "photo",
            "notes",
            "meta",
        ]

    def validate_student(self, student):
        if self.instance and (getattr(self.instance, "give_access", False) or self.instance.portal_state != "unverified") and student.pk != self.instance.student_id:
            raise serializers.ValidationError(
                "Portal guardian relationships cannot be moved to another student. Create and approve a new relationship."
            )
        return student

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["full_name"] = instance.full_name
        response["student"] = instance.student.id_number
        response["photo"] = instance.photo or instance.default_photo
        request = self.context.get("request")
        if request:
            from authorization.services import get_assigned_role
            role = get_assigned_role(request.user)
            if role and role.system_key == "parent":
                for field in ("notes", "meta", "parent_profile_id", "portal_verified_at", "give_access"):
                    response.pop(field, None)
        return response

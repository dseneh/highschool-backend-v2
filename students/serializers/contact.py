from common.update_utils import ChangedFieldsModelSerializerMixin, PartialUpdateModelSerializer

from rest_framework import serializers


from ..models import StudentContact


class StudentContactSerializer(ChangedFieldsModelSerializerMixin, PartialUpdateModelSerializer):
    class Meta:
        model = StudentContact
        read_only_fields = ["portal_guardian_id"]
        fields = [
            "portal_guardian_id",
            "id",
            "student",
            "first_name",
            "middle_name",
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
        guardian = instance.student.guardians.filter(pk=instance.portal_guardian_id).first() if instance.portal_guardian_id else None
        response["give_access"] = bool(guardian and guardian.give_access)
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

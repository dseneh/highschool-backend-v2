from rest_framework import serializers

from authorization.models import Role, RolePermission


class RolePermissionSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source="permission_code")

    class Meta:
        model = RolePermission
        fields = ("code", "scope")


class RoleSerializer(serializers.ModelSerializer):
    permissions = RolePermissionSerializer(
        source="permission_grants",
        many=True,
        read_only=True,
    )
    user_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Role
        fields = (
            "id",
            "name",
            "description",
            "system_key",
            "is_system_role",
            "is_default",
            "is_active",
            "permission_version",
            "user_count",
            "permissions",
            "created_at",
            "updated_at",
        )


class UnifiedRoleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    system_key = serializers.CharField(allow_null=True, required=False)
    is_system_role = serializers.BooleanField()
    role_type = serializers.CharField()
    scope = serializers.CharField()
    is_active = serializers.BooleanField()
    permission_version = serializers.IntegerField()
    user_count = serializers.IntegerField(default=0)
    permissions = serializers.ListField(child=serializers.DictField(), default=list)


class PermissionGrantInputSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=150)
    scope = serializers.ChoiceField(choices=("own", "assigned", "all"))


class PermissionListValidationMixin:
    def validate_permissions(self, permissions):
        codes = [grant["code"] for grant in permissions]
        if len(codes) != len(set(codes)):
            raise serializers.ValidationError("Each permission may only be granted once.")
        return permissions


class RoleWriteSerializer(PermissionListValidationMixin, serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=100)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(required=False, default=True)
    permissions = PermissionGrantInputSerializer(many=True, required=False)


class RoleUpdateSerializer(PermissionListValidationMixin, serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=100, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    permissions = PermissionGrantInputSerializer(many=True, required=False)


class RoleCloneSerializer(PermissionListValidationMixin, serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=100)
    description = serializers.CharField(required=False, allow_blank=True)
    permissions = PermissionGrantInputSerializer(many=True, required=False)


class RolePermissionReplacementSerializer(PermissionListValidationMixin, serializers.Serializer):
    permissions = PermissionGrantInputSerializer(many=True)


class UserRoleAssignmentSerializer(serializers.Serializer):
    role_id = serializers.UUIDField()


class BulkUserRoleAssignmentSerializer(UserRoleAssignmentSerializer):
    id_numbers = serializers.ListField(
        child=serializers.CharField(max_length=50),
        allow_empty=False,
    )

    def validate_id_numbers(self, id_numbers):
        normalized = [value.strip() for value in id_numbers if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise serializers.ValidationError("Each user may only be assigned once.")
        return normalized

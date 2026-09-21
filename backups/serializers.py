from rest_framework import serializers

from backups.models import TenantBackup, TenantRestoreRequest


class TenantBackupSerializer(serializers.ModelSerializer):
    requested_by = serializers.SerializerMethodField()

    class Meta:
        model = TenantBackup
        fields = (
            "id",
            "backup_type",
            "status",
            "reason",
            "requested_by",
            "requested_at",
            "started_at",
            "completed_at",
            "file_size",
            "sha256",
            "postgres_version",
            "application_version",
            "expires_at",
        )
        read_only_fields = fields

    def get_requested_by(self, obj):
        return _user_summary(obj.requested_by)


class PlatformTenantBackupSerializer(TenantBackupSerializer):
    tenant_id = serializers.UUIDField(source="tenant.id", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    tenant_schema = serializers.CharField(source="tenant.schema_name", read_only=True)

    class Meta(TenantBackupSerializer.Meta):
        fields = (
            "tenant_id",
            "tenant_name",
            "tenant_schema",
            *TenantBackupSerializer.Meta.fields,
        )
        read_only_fields = fields


class BackupRequestCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, allow_blank=False, max_length=2000, trim_whitespace=True)


class TenantRestoreRequestSerializer(serializers.ModelSerializer):
    requested_by = serializers.SerializerMethodField()
    approved_by = serializers.SerializerMethodField()
    rejected_by = serializers.SerializerMethodField()
    backup_id = serializers.UUIDField(source="backup.id", read_only=True)
    safety_backup_id = serializers.UUIDField(source="safety_backup.id", read_only=True, allow_null=True)
    tenant_id = serializers.UUIDField(source="tenant.id", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    tenant_schema = serializers.CharField(source="tenant.schema_name", read_only=True)

    class Meta:
        model = TenantRestoreRequest
        fields = (
            "id",
            "tenant_id",
            "tenant_name",
            "tenant_schema",
            "backup_id",
            "safety_backup_id",
            "status",
            "reason",
            "requested_by",
            "requested_at",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "decision_note",
            "started_at",
            "completed_at",
        )
        read_only_fields = fields

    def get_requested_by(self, obj):
        return _user_summary(obj.requested_by)

    def get_approved_by(self, obj):
        return _user_summary(obj.approved_by)

    def get_rejected_by(self, obj):
        return _user_summary(obj.rejected_by)


class PlatformTenantRestoreRequestSerializer(TenantRestoreRequestSerializer):
    class Meta(TenantRestoreRequestSerializer.Meta):
        fields = (
            *TenantRestoreRequestSerializer.Meta.fields,
            "error_message",
        )
        read_only_fields = fields


class RestoreRequestCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class RestoreDecisionSerializer(serializers.Serializer):
    decision_note = serializers.CharField(required=False, allow_blank=True, max_length=2000)


def _user_summary(user):
    if user is None:
        return None
    display_name = " ".join(
        part for part in (getattr(user, "first_name", ""), getattr(user, "last_name", "")) if part
    ).strip()
    return {
        "id": str(user.pk),
        "id_number": getattr(user, "id_number", None),
        "name": display_name or getattr(user, "email", "") or str(user.pk),
    }


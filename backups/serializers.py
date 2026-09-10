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


class TenantRestoreRequestSerializer(serializers.ModelSerializer):
    requested_by = serializers.SerializerMethodField()
    approved_by = serializers.SerializerMethodField()
    rejected_by = serializers.SerializerMethodField()
    backup_id = serializers.UUIDField(source="backup.id", read_only=True)
    safety_backup_id = serializers.UUIDField(source="safety_backup.id", read_only=True, allow_null=True)

    class Meta:
        model = TenantRestoreRequest
        fields = (
            "id",
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


class RestoreRequestCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


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

from rest_framework import serializers

from backups.models import TenantBackup


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
        user = obj.requested_by
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

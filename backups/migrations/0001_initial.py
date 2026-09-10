import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0012_tenant_billing_subscription_workflow_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantBackup",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("schema_name", models.CharField(max_length=63)),
                ("backup_type", models.CharField(choices=[("manual", "Manual"), ("scheduled", "Scheduled"), ("pre_restore", "Pre-restore"), ("system", "System")], default="manual", max_length=20)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("preparing", "Preparing"), ("backing_up", "Backing up"), ("uploading", "Uploading"), ("verifying", "Verifying"), ("available", "Available"), ("failed", "Failed"), ("expired", "Expired"), ("deleting", "Deleting"), ("deleted", "Deleted")], db_index=True, default="queued", max_length=20)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("storage_provider", models.CharField(blank=True, default="", max_length=30)),
                ("storage_key", models.CharField(blank=True, default="", max_length=1024)),
                ("file_size", models.PositiveBigIntegerField(blank=True, null=True)),
                ("sha256", models.CharField(blank=True, default="", max_length=64)),
                ("postgres_version", models.CharField(blank=True, default="", max_length=100)),
                ("application_version", models.CharField(blank=True, default="", max_length=100)),
                ("error_message", models.TextField(blank=True, default="")),
                ("expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requested_tenant_backups", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="backups", to="core.tenant")),
            ],
            options={"db_table": "backups_tenant_backup", "ordering": ("-requested_at",)},
        ),
        migrations.AddIndex(
            model_name="tenantbackup",
            index=models.Index(fields=["tenant", "status", "-requested_at"], name="backup_tenant_status_idx"),
        ),
    ]

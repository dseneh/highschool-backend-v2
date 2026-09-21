from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("backups", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantRestoreRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("schema_name", models.CharField(max_length=63)),
                ("status", models.CharField(choices=[("requested", "Requested"), ("safety_backup_pending", "Safety backup pending"), ("ready_for_approval", "Ready for approval"), ("approved", "Approved"), ("rejected", "Rejected"), ("restoring", "Restoring"), ("completed", "Completed"), ("failed", "Failed"), ("cancelled", "Cancelled")], db_index=True, default="requested", max_length=30)),
                ("reason", models.TextField(blank=True, default="")),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("rejected_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.TextField(blank=True, default="")),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_tenant_restores", to=settings.AUTH_USER_MODEL)),
                ("backup", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="restore_requests", to="backups.tenantbackup")),
                ("rejected_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="rejected_tenant_restores", to=settings.AUTH_USER_MODEL)),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requested_tenant_restores", to=settings.AUTH_USER_MODEL)),
                ("safety_backup", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="safety_backup_for_restore_requests", to="backups.tenantbackup")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="restore_requests", to="core.tenant")),
            ],
            options={
                "db_table": "backups_tenant_restore_request",
                "ordering": ("-requested_at",),
            },
        ),
        migrations.AddIndex(
            model_name="tenantrestorerequest",
            index=models.Index(fields=["tenant", "status", "-requested_at"], name="restore_tenant_status_idx"),
        ),
    ]

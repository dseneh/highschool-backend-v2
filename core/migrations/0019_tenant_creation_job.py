import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_feature_entitlements"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantCreationJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source_schema", models.CharField(blank=True, default="", max_length=63)),
                ("destination_schema", models.CharField(db_index=True, max_length=63)),
                ("selected_modules", models.JSONField(default=list)),
                ("request_payload", models.JSONField(default=dict)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("in_progress", "In progress"), ("completed", "Completed"), ("failed", "Failed")], default="pending", max_length=20)),
                ("stage", models.CharField(default="Queued", max_length=80)),
                ("progress_percent", models.PositiveSmallIntegerField(default=0)),
                ("failure_detail", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("destination_tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="creation_jobs", to="core.tenant")),
                ("requested_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requested_tenant_creation_jobs", to=settings.AUTH_USER_MODEL)),
                ("source_tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="clone_source_jobs", to="core.tenant")),
            ],
            options={
                "db_table": "core_tenant_creation_job",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="tenantcreationjob",
            index=models.Index(fields=["destination_schema", "status"], name="core_tenant_destina_dac0e8_idx"),
        ),
        migrations.AddConstraint(
            model_name="tenantcreationjob",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["pending", "in_progress"])),
                fields=("destination_schema",),
                name="unique_active_tenant_creation_destination",
            ),
        ),
    ]

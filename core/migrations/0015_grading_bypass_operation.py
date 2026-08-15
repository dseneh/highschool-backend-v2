import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_rename_tenant_owner_activation_indexes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GradingBypassOperation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("academic_year_id", models.CharField(max_length=64)),
                ("academic_year_name", models.CharField(max_length=255)),
                ("reason", models.TextField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("failed", "Failed")], default="pending", max_length=20)),
                ("preview", models.JSONField(blank=True, default=dict)),
                ("deleted_records", models.JSONField(blank=True, default=dict)),
                ("financial_adjustments", models.JSONField(blank=True, default=dict)),
                ("year_end_records_updated", models.PositiveIntegerField(default=0)),
                ("failure_detail", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("executed_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="executed_grading_bypasses", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="grading_bypass_operations", to="core.tenant")),
            ],
            options={"db_table": "core_grading_bypass_operation", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="gradingbypassoperation",
            index=models.Index(fields=["tenant", "academic_year_id", "status"], name="core_gradin_tenant__0f3e27_idx"),
        ),
    ]
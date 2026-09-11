from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("backups", "0005_add_execution_pending_status"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupPlatformSettings",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("automatic_backups_enabled", models.BooleanField(default=True)),
                ("frequency", models.CharField(choices=[("daily", "Daily"), ("weekly", "Weekly")], default="weekly", max_length=20)),
                ("scheduled_time", models.TimeField(default="02:00")),
                ("timezone", models.CharField(default="UTC", max_length=64)),
                ("scheduled_retention_days", models.PositiveIntegerField(default=30)),
                ("manual_retention_days", models.PositiveIntegerField(default=30)),
                ("safety_retention_days", models.PositiveIntegerField(default=14)),
                ("system_retention_days", models.PositiveIntegerField(default=30)),
                ("maximum_retained_scheduled_backups", models.PositiveIntegerField(default=8)),
                ("tenant_manual_backups_allowed", models.BooleanField(default=True)),
                ("tenant_restore_requests_allowed", models.BooleanField(default=True)),
                ("tenant_restore_execution_allowed", models.BooleanField(default=True)),
                ("default_storage_quota_bytes", models.PositiveBigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name_plural": "Backup platform settings",
                "db_table": "backups_platform_settings",
            },
        ),
        migrations.CreateModel(
            name="TenantBackupPolicy",
            fields=[
                ("automatic_backups_enabled", models.BooleanField(blank=True, null=True)),
                ("frequency", models.CharField(blank=True, choices=[("daily", "Daily"), ("weekly", "Weekly")], max_length=20, null=True)),
                ("scheduled_time", models.TimeField(blank=True, null=True)),
                ("timezone", models.CharField(blank=True, default="", max_length=64)),
                ("scheduled_retention_days", models.PositiveIntegerField(blank=True, null=True)),
                ("manual_retention_days", models.PositiveIntegerField(blank=True, null=True)),
                ("safety_retention_days", models.PositiveIntegerField(blank=True, null=True)),
                ("system_retention_days", models.PositiveIntegerField(blank=True, null=True)),
                ("maximum_retained_scheduled_backups", models.PositiveIntegerField(blank=True, null=True)),
                ("manual_backups_allowed", models.BooleanField(blank=True, null=True)),
                ("restore_requests_allowed", models.BooleanField(blank=True, null=True)),
                ("restore_execution_allowed", models.BooleanField(blank=True, null=True)),
                ("storage_quota_bytes", models.PositiveBigIntegerField(blank=True, null=True)),
                ("storage_quota_overridden", models.BooleanField(default=False)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("next_run_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name="backup_policy", serialize=False, to="core.tenant")),
            ],
            options={
                "db_table": "backups_tenant_policy",
            },
        ),
        migrations.AddIndex(
            model_name="tenantbackuppolicy",
            index=models.Index(fields=["next_run_at"], name="backup_policy_next_run_idx"),
        ),
    ]

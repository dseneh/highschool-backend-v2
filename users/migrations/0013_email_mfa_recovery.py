import django.db.models.deletion
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0012_tenantsession_device_metadata")]

    operations = [
        migrations.CreateModel(
            name="EmailMFARecovery",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("tenant_schema", models.CharField(db_index=True, max_length=63)),
                ("new_email", models.EmailField(max_length=254)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("code_hash", models.CharField(max_length=128)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("failed_attempts", models.PositiveSmallIntegerField(default=0)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("invalidated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "initiated_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="initiated_email_mfa_recoveries",
                        to="users.user",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_mfa_recoveries",
                        to="users.user",
                    ),
                ),
            ],
            options={"db_table": "user_email_mfa_recovery"},
        ),
        migrations.AddIndex(
            model_name="emailmfarecovery",
            index=models.Index(
                fields=["user", "tenant_schema", "created_at"],
                name="user_mfa_recovery_idx",
            ),
        ),
    ]

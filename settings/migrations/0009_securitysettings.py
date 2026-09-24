import django.db.models.deletion
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("settings", "0008_gradingsettings_allow_grade_view_with_outstanding_balance"),
        ("users", "0013_email_mfa_recovery"),
    ]

    operations = [
        migrations.CreateModel(
            name="SecuritySettings",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("require_mfa_for_payroll_approval", models.BooleanField(default=False)),
                ("require_mfa_for_payment_configuration", models.BooleanField(default=False)),
                ("require_mfa_for_bank_account_changes", models.BooleanField(default=False)),
                ("require_mfa_for_backup_restore", models.BooleanField(default=False)),
                ("require_mfa_for_security_settings", models.BooleanField(default=False)),
                ("require_mfa_for_admin_role_changes", models.BooleanField(default=False)),
                ("require_mfa_for_mfa_recovery", models.BooleanField(default=False)),
                ("created_by", models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_securitysettings_set", to="users.user")),
                ("updated_by", models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_securitysettings_set", to="users.user")),
            ],
            options={
                "verbose_name": "Security Settings",
                "verbose_name_plural": "Security Settings",
                "db_table": "security_settings",
            },
        ),
    ]

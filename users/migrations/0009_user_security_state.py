from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0008_merge_role_and_rbac_histories")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="security_version",
            field=models.PositiveBigIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="user",
            name="mfa_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="mfa_required",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="mfa_secret_envelope",
            field=models.JSONField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="mfa_confirmed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="mfa_recovery_code_hashes",
            field=models.JSONField(blank=True, default=list, editable=False),
        ),
    ]

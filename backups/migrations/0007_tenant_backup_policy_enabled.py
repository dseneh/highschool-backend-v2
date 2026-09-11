from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("backups", "0006_backup_platform_settings_tenant_policy")]

    operations = [
        migrations.AddField(
            model_name="tenantbackuppolicy",
            name="backups_enabled",
            field=models.BooleanField(default=True),
        ),
    ]

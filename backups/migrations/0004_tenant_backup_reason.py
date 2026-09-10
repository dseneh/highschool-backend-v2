from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("backups", "0003_tenant_restore_runtime_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantbackup",
            name="reason",
            field=models.TextField(blank=True, default=""),
        ),
    ]

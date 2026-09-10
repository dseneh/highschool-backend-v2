from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("backups", "0002_tenant_restore_request"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantrestorerequest",
            name="tenant_runtime_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

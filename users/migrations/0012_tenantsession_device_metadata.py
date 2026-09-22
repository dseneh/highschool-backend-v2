from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0011_email_mfa_challenge")]

    operations = [
        migrations.AddField(
            model_name="tenantsession",
            name="device_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

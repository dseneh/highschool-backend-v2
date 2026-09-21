from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0025_shared_role_assignments")]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="restoration_in_progress",
            field=models.BooleanField(
                default=False,
                help_text="Hard tenant-wide gate while a schema restoration is running.",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="restoration_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="restoration_request_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]

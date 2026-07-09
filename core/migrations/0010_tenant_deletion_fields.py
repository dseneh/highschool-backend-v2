from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_tenant_provisioning_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="deletion_status",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                ],
                default="none",
                help_text="Background deletion job status.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="deletion_mode",
            field=models.CharField(
                blank=True,
                choices=[("", "None"), ("soft", "Soft"), ("hard", "Hard")],
                default="",
                help_text="Pending or last deletion mode: soft (retain data) or hard (drop schema).",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="deletion_step",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Current deletion step key.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="deletion_progress",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Deletion progress percentage (0-100).",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="deletion_error",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Last deletion failure message, if any.",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="deletion_completed_steps",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Completed deletion step keys (used for resume/retry).",
            ),
        ),
    ]

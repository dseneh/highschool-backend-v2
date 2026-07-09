from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_tenant_billing_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="provisioning_status",
            field=models.CharField(
                choices=[
                    ("completed", "Completed"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("failed", "Failed"),
                ],
                default="completed",
                help_text="Background workspace setup status. 'completed' for fully provisioned tenants.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="provisioning_step",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Current provisioning step key (e.g. create_schema, provision_defaults).",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="provisioning_progress",
            field=models.PositiveSmallIntegerField(
                default=100,
                help_text="Provisioning progress percentage (0-100).",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="provisioning_error",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Last provisioning failure message, if any.",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="provisioning_completed_steps",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="List of completed provisioning step keys (used for resume/retry).",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="provisioning_payload",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Stored create payload (domain, desired active/status, etc.) for retry.",
            ),
        ),
    ]

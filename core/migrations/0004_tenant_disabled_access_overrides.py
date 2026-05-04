from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_tenant_runtime_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="disabled_access_allow_tenant_admins",
            field=models.BooleanField(
                default=True,
                help_text="When workspace access is disabled, tenant admins can still access explicitly allowed pages.",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="disabled_access_allowed_paths",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="List of tenant page path prefixes allowed while workspace is disabled (for approved users/admins).",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="disabled_access_allowed_users",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="List of user identifiers (id_number/username/email) allowed on disabled workspace override paths.",
            ),
        ),
    ]

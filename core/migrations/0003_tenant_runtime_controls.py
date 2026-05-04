from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="maintenance_mode",
            field=models.BooleanField(
                default=False,
                help_text="When enabled, tenant workspace operations are paused except for allowed auth/status checks.",
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="login_access_policy",
            field=models.CharField(
                choices=[
                    ("all_users", "All Users"),
                    ("tenant_admin_only", "Tenant Admin Only"),
                    ("disabled", "Disabled"),
                ],
                default="all_users",
                help_text="Controls who can sign in to this tenant workspace.",
                max_length=32,
            ),
        ),
    ]
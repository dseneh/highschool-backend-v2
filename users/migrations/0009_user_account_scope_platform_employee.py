import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def initialize_account_scope(apps, schema_editor):
    User = apps.get_model("users", "User")
    # Preserve legacy GLOBAL semantics during the staged refactor. Tenant/global
    # memberships will be used to refine this in a later data migration.
    User.objects.filter(account_type="global").update(account_scope="platform_and_tenant")


class Migration(migrations.Migration):
    dependencies = [("users", "0008_merge_role_and_rbac_histories")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="account_scope",
            field=models.CharField(
                choices=[
                    ("tenant", "Tenant"),
                    ("platform", "Platform"),
                    ("platform_and_tenant", "Platform And Tenant"),
                ],
                default="tenant",
                help_text="Workspace eligibility boundary. Actual authorization still requires role assignments/memberships.",
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="PlatformEmployee",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("employee_number", models.CharField(blank=True, max_length=50, null=True, unique=True)),
                ("position", models.CharField(blank=True, default="", max_length=150)),
                ("department", models.CharField(blank=True, default="", max_length=150)),
                ("status", models.CharField(choices=[("active", "Active"), ("inactive", "Inactive"), ("terminated", "Terminated")], default="active", max_length=20)),
                ("hire_date", models.DateField(blank=True, null=True)),
                ("termination_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="platform_employment", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "platform_employee", "ordering": ("user__last_name", "user__first_name")},
        ),
        migrations.RunPython(initialize_account_scope, migrations.RunPython.noop),
    ]

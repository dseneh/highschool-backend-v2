from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0004_remove_legacy_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="account_type",
            field=models.CharField(
                choices=[
                    ("student", "Student"),
                    ("global", "Global"),
                    ("staff", "Staff"),
                    ("parent", "Parent"),
                    ("other", "Other"),
                ],
                default="other",
                help_text="Identity category only: global, staff, student, parent, or other. Authorization is tenant RBAC.",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="is_default_password",
            field=models.BooleanField(
                default=False,
                help_text="Indicates whether this account is using its default password.",
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="photo",
            field=models.ImageField(
                blank=True,
                help_text="User profile photo (storage backend handles tenant isolation)",
                null=True,
                upload_to="users",
            ),
        ),
    ]

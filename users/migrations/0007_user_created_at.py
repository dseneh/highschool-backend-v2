from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0006_user_profile_audit_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True,
                blank=True,
                help_text="Time this user account was created.",
                null=True,
            ),
        ),
    ]
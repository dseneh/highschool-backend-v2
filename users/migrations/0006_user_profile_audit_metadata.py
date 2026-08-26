from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0005_update_user_identity_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="profile_updated_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Last time profile or account details were updated.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="profile_updated_by",
            field=models.ForeignKey(
                blank=True,
                help_text="User who last updated this account's profile details.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="profile_updates_made",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
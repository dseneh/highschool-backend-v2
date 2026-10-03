import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0010_alter_user_photo"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailMFAChallenge",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_schema", models.CharField(db_index=True, max_length=63)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("code_hash", models.CharField(max_length=128)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("failed_attempts", models.PositiveSmallIntegerField(default=0)),
                ("resend_count", models.PositiveSmallIntegerField(default=0)),
                ("last_sent_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("invalidated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="email_mfa_challenges", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "user_email_mfa_challenge"},
        ),
        migrations.AddIndex(
            model_name="emailmfachallenge",
            index=models.Index(fields=["user", "tenant_schema", "created_at"], name="user_mfa_user_tenant_idx"),
        ),
    ]

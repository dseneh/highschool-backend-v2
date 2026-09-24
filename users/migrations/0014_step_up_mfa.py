import django.db.models.deletion
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0013_email_mfa_recovery")]

    operations = [
        migrations.AddField(model_name="emailmfachallenge", name="action", field=models.CharField(blank=True, default="", max_length=64)),
        migrations.AddField(model_name="emailmfachallenge", name="context", field=models.CharField(blank=True, default="", max_length=255)),
        migrations.AddField(model_name="emailmfachallenge", name="purpose", field=models.CharField(db_index=True, default="login", max_length=32)),
        migrations.CreateModel(
            name="StepUpAuthorization",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_schema", models.CharField(db_index=True, max_length=63)),
                ("action", models.CharField(db_index=True, max_length=64)),
                ("context", models.CharField(blank=True, default="", max_length=255)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="step_up_authorizations", to="users.user")),
            ],
            options={"db_table": "user_step_up_authorization"},
        ),
        migrations.AddIndex(
            model_name="stepupauthorization",
            index=models.Index(fields=["user", "tenant_schema", "action", "expires_at"], name="user_step_up_lookup_idx"),
        ),
    ]

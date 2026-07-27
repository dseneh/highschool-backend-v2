from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
        ("core", "0012_tenant_billing_subscription_workflow_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantOwnerActivationCode",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("purpose", models.CharField(choices=[("tenant_owner_activation", "Tenant owner activation")], default="tenant_owner_activation", max_length=50)),
                ("code_hash", models.CharField(max_length=255)),
                ("delivered_to", models.EmailField(blank=True, default="", max_length=254)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("last_sent_at", models.DateTimeField(auto_now_add=True)),
                ("failed_attempts", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("issued_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="issued_tenant_activation_codes", to="users.user")),
                ("signup_request", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activation_codes", to="core.signuprequest")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="owner_activation_codes", to="core.tenant")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tenant_activation_codes", to="users.user")),
            ],
            options={
                "db_table": "tenant_owner_activation_code",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="tenantowneractivationcode",
            index=models.Index(fields=["tenant", "user", "purpose"], name="tenant_owne_tenant__e35c4c_idx"),
        ),
        migrations.AddIndex(
            model_name="tenantowneractivationcode",
            index=models.Index(fields=["expires_at"], name="tenant_owne_expires_7d6407_idx"),
        ),
        migrations.AddIndex(
            model_name="tenantowneractivationcode",
            index=models.Index(fields=["used_at"], name="tenant_owne_used_at_b20f56_idx"),
        ),
    ]
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_payroll_feature(apps, schema_editor):
    Feature = apps.get_model("core", "Feature")
    Tenant = apps.get_model("core", "Tenant")
    Entitlement = apps.get_model("core", "TenantFeatureEntitlement")

    payroll, _ = Feature.objects.get_or_create(
        key="payroll",
        defaults={
            "name": "Payroll",
            "description": "Payroll runs, compensation, salary advances, and employee benefits.",
            "category": "Financial management",
        },
    )
    for tenant in Tenant.objects.exclude(schema_name="public"):
        Entitlement.objects.get_or_create(
            tenant=tenant,
            feature=payroll,
            defaults={"source": "grandfathered", "status": "active", "locally_enabled": True},
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0017_alter_gradingbypassoperation_status"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Feature",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(max_length=80, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True, default="")),
                ("category", models.CharField(blank=True, default="", max_length=80)),
                ("is_purchasable", models.BooleanField(default=True)),
                ("stripe_price_id", models.CharField(blank=True, default="", max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "core_feature", "ordering": ["category", "name"]},
        ),
        migrations.CreateModel(
            name="TenantFeatureEntitlement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(choices=[("addon", "Add-on"), ("plan", "Plan"), ("complimentary", "Complimentary"), ("grandfathered", "Grandfathered")], default="addon", max_length=24)),
                ("status", models.CharField(choices=[("active", "Active"), ("pending_payment", "Pending payment"), ("ended", "Ended")], default="active", max_length=24)),
                ("locally_enabled", models.BooleanField(default=True)),
                ("cancel_at_period_end", models.BooleanField(default=False)),
                ("active_from", models.DateTimeField(blank=True, null=True)),
                ("active_until", models.DateTimeField(blank=True, null=True)),
                ("stripe_subscription_item_id", models.CharField(blank=True, default="", max_length=255)),
                ("limits", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("feature", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tenant_entitlements", to="core.feature")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feature_entitlements", to="core.tenant")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_feature_entitlements", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "core_tenant_feature_entitlement"},
        ),
        migrations.CreateModel(
            name="TenantFeatureChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("enabled", "Enabled"), ("locally_disabled", "Locally disabled"), ("locally_enabled", "Locally enabled"), ("cancellation_scheduled", "Cancellation scheduled"), ("cancellation_resumed", "Cancellation resumed")], max_length=32)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="feature_changes", to=settings.AUTH_USER_MODEL)),
                ("entitlement", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="changes", to="core.tenantfeatureentitlement")),
                ("feature", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tenant_changes", to="core.feature")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feature_changes", to="core.tenant")),
            ],
            options={"db_table": "core_tenant_feature_change", "ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(model_name="tenantfeatureentitlement", constraint=models.UniqueConstraint(fields=("tenant", "feature"), name="core_tenant_feature_unique")),
        migrations.RunPython(seed_payroll_feature, migrations.RunPython.noop),
    ]

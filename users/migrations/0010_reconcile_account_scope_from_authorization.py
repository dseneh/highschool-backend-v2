from django.db import migrations
from django.db.models import Q
from django_tenants.utils import get_public_schema_name, schema_context


def reconcile_account_scope(apps, schema_editor):
    User = apps.get_model("users", "User")
    Tenant = apps.get_model("core", "Tenant")
    SharedRoleAssignment = apps.get_model("core", "SharedRoleAssignment")
    TenantMembership = apps.get_model("authorization", "TenantMembership")

    public_schema = get_public_schema_name()

    with schema_context(public_schema):
        users = list(User.objects.all().only("id", "account_scope"))
        platform_user_ids = set(
            SharedRoleAssignment.objects.filter(
                is_active=True,
                role__is_active=True,
                role__scope__in=["PUBLIC", "GLOBAL"],
            ).values_list("user_id", flat=True)
        )
        tenant_schemas = list(
            Tenant.objects.exclude(schema_name=public_schema)
            .exclude(status="deleted")
            .values_list("schema_name", flat=True)
        )

    tenant_user_ids = set()
    for schema_name in tenant_schemas:
        try:
            with schema_context(schema_name):
                tenant_user_ids.update(
                    TenantMembership.objects.filter(is_active=True)
                    .filter(Q(role__is_active=True) | Q(shared_role_id__isnull=False))
                    .values_list("user_id", flat=True)
                )
        except Exception:
            # A partially-created or historical tenant schema should not block
            # the public migration. Runtime scope synchronization will reconcile
            # the user again when that tenant becomes healthy.
            continue

    with schema_context(public_schema):
        for user in users:
            platform = user.id in platform_user_ids
            tenant = user.id in tenant_user_ids
            if platform and tenant:
                desired = "platform_and_tenant"
            elif platform:
                desired = "platform"
            else:
                desired = "tenant"
            if user.account_scope != desired:
                User.objects.filter(pk=user.pk).update(account_scope=desired)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0009_user_account_scope_platform_employee"),
        ("core", "0025_shared_role_assignments"),
        ("authorization", "0003_tenant_membership_shared_role"),
    ]

    operations = [
        migrations.RunPython(reconcile_account_scope, migrations.RunPython.noop),
    ]

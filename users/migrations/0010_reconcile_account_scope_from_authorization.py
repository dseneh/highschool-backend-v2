from django.db import migrations
from django_tenants.utils import get_public_schema_name, schema_context


def reconcile_account_scope(apps, schema_editor):
    """Reconcile identity scope using data available on the public schema.

    ``authorization`` is a tenant-only app, so a shared ``users`` migration
    cannot depend on or load its migration state. Tenant presence is therefore
    derived from django-tenant-users' public user<->tenant association. Public
    role assignments remain the source of truth for platform access.

    Runtime authorization/membership services can further reconcile scope as
    tenant RBAC assignments change after this one-time migration.
    """
    User = apps.get_model("users", "User")
    SharedRoleAssignment = apps.get_model("core", "SharedRoleAssignment")

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
        tenant_user_ids = set(
            User.tenants.through.objects.values_list("user_id", flat=True).distinct()
        )

        for user in users:
            platform = user.id in platform_user_ids
            tenant = user.id in tenant_user_ids

            if platform and tenant:
                desired = "platform_and_tenant"
            elif platform:
                desired = "platform"
            else:
                # Identities without platform access remain tenant-scoped. This
                # includes unassigned/orphan identities that administrators may
                # need to reconcile later; they must never gain platform access
                # merely because historical account_type was ``global``.
                desired = "tenant"

            if user.account_scope != desired:
                User.objects.filter(pk=user.pk).update(account_scope=desired)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0009_user_account_scope_platform_employee"),
        ("core", "0025_shared_role_assignments"),
    ]

    operations = [
        migrations.RunPython(reconcile_account_scope, migrations.RunPython.noop),
    ]

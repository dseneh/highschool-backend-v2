from django.db import migrations
from django_tenants.utils import get_public_schema_name, schema_context


def backfill(apps, schema_editor):
    Membership = apps.get_model("authorization", "TenantMembership")
    Assignment = apps.get_model("authorization", "TenantRoleAssignment")
    SharedRole = apps.get_model("core", "SharedRole")
    with schema_context(get_public_schema_name()):
        shared_keys = dict(SharedRole.objects.values_list("pk", "system_key"))
    for membership in Membership.objects.select_related("role").iterator():
        if membership.role_id:
            key = membership.role.system_key
            identity = f"authorization.role:{membership.role_id}"
        else:
            key = shared_keys.get(membership.shared_role_id)
            identity = f"core.sharedrole:{membership.shared_role_id}"
        Assignment.objects.get_or_create(
            membership=membership,
            role_key=f"system:{key}" if key else identity,
            defaults={"role_id": membership.role_id, "shared_role_id": membership.shared_role_id,
                      "is_active": membership.is_active},
        )


class Migration(migrations.Migration):
    dependencies = [("authorization", "0004_tenantroleassignment"), ("core", "0025_shared_role_assignments")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]

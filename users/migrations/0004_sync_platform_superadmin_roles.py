from django.db import migrations



def sync_platform_superadmin_roles(apps, schema_editor):
    if schema_editor.connection.schema_name != "public":
        return

    User = apps.get_model("users", "User")
    UserTenantPermissions = apps.get_model("permissions", "UserTenantPermissions")
    platform_superuser_ids = UserTenantPermissions.objects.filter(
        is_superuser=True,
    ).values_list("profile_id", flat=True)
    User.objects.filter(pk__in=platform_superuser_ids).update(role="superadmin")


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_reconcile_user_role_column"),
    ]

    operations = [
        migrations.RunPython(sync_platform_superadmin_roles, migrations.RunPython.noop),
    ]

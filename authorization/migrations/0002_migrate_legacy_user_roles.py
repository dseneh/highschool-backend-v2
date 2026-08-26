from django.db import migrations


def migrate_legacy_user_roles(apps, schema_editor):
    Role = apps.get_model("authorization", "Role")
    TenantMembership = apps.get_model("authorization", "TenantMembership")
    User = apps.get_model("users", "User")

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = %s AND column_name = 'role'
            )
            """,
            [User._meta.db_table],
        )
        has_legacy_role_column = cursor.fetchone()[0]
    if not has_legacy_role_column:
        return

    legacy_roles = dict(
        User.objects.filter(
            pk__in=TenantMembership.objects.values_list("user_id", flat=True),
        ).values_list("pk", "role")
    )
    for membership in TenantMembership.objects.select_related("role"):
        legacy_role = legacy_roles.get(membership.user_id)
        if not legacy_role or membership.role.system_key != "viewer":
            continue
        mapped_role = Role.objects.filter(
            system_key=str(legacy_role).lower(),
            is_active=True,
        ).first()
        if mapped_role is not None:
            membership.role = mapped_role
            membership.save(update_fields=("role",))


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0001_initial"),
        ("users", "0003_remove_legacy_privileges"),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_user_roles, migrations.RunPython.noop),
    ]

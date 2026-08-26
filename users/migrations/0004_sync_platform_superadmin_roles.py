from django.db import migrations



def sync_platform_superadmin_roles(apps, schema_editor):
    if schema_editor.connection.schema_name != "public":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'user'
                  AND column_name = 'role'
            )
            """
        )
        if not cursor.fetchone()[0]:
            return
        cursor.execute(
            """
            UPDATE "user"
            SET role = 'superadmin'
            WHERE id IN (
                SELECT profile_id
                FROM permissions_usertenantpermissions
                WHERE is_superuser = TRUE
            )
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_reconcile_user_role_column"),
    ]

    operations = [
        migrations.RunPython(sync_platform_superadmin_roles, migrations.RunPython.noop),
    ]

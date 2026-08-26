from django.db import migrations, models


def migrate_platform_superusers(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.filter(role="superadmin").update(is_platform_superuser=True)


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0002_migrate_legacy_user_roles"),
        ("users", "0003_remove_legacy_privileges"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_platform_superuser",
            field=models.BooleanField(
                default=False,
                help_text="Platform-wide administration flag. Tenant authorization uses RBAC memberships.",
            ),
        ),
        migrations.RunPython(migrate_platform_superusers, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="user",
            name="role",
        ),
    ]

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0007_user_created_at"),
        ("users", "0004_sync_platform_superadmin_roles"),
    ]

    operations = []

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_tenant_owner_activation_code"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="tenantowneractivationcode",
            old_name="tenant_owne_tenant__e35c4c_idx",
            new_name="tenant_owne_tenant__dc4bf6_idx",
        ),
        migrations.RenameIndex(
            model_name="tenantowneractivationcode",
            old_name="tenant_owne_expires_7d6407_idx",
            new_name="tenant_owne_expires_fbcf75_idx",
        ),
        migrations.RenameIndex(
            model_name="tenantowneractivationcode",
            old_name="tenant_owne_used_at_b20f56_idx",
            new_name="tenant_owne_used_at_ec57cc_idx",
        ),
    ]
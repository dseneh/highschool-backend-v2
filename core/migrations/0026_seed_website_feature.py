from django.db import migrations


def seed_website_feature(apps, schema_editor):
    Feature = apps.get_model("core", "Feature")
    Feature.objects.update_or_create(
        key="website",
        defaults={
            "name": "School Website",
            "description": "A public school website with templates, pages, media, and online admissions.",
            "category": "Engagement",
            "is_purchasable": True,
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0025_shared_role_assignments")]

    operations = [migrations.RunPython(seed_website_feature, migrations.RunPython.noop)]

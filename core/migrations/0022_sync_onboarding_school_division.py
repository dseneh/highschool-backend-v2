from django.db import migrations


def sync_onboarding_school_division(apps, schema_editor):
    Tenant = apps.get_model("core", "Tenant")

    for tenant in Tenant.objects.exclude(onboarding_plan__isnull=True).iterator():
        plan = tenant.onboarding_plan
        if not isinstance(plan, dict):
            continue
        steps = plan.get("steps")
        if not isinstance(steps, dict):
            continue
        school_profile = steps.get("school_profile")
        if not isinstance(school_profile, dict):
            continue
        payload = school_profile.get("payload")
        if not isinstance(payload, dict):
            continue

        expected = str(tenant.school_division_id) if tenant.school_division_id else ""
        if payload.get("school_division") == expected:
            continue

        payload["school_division"] = expected
        tenant.onboarding_plan = plan
        tenant.save(update_fields=["onboarding_plan"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0021_shared_division_catalog"),
    ]

    operations = [
        migrations.RunPython(
            sync_onboarding_school_division,
            migrations.RunPython.noop,
        ),
    ]

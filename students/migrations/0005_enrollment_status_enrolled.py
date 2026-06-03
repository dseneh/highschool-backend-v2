from django.db import migrations


def completed_to_enrolled(apps, schema_editor):
    Enrollment = apps.get_model("students", "Enrollment")
    Enrollment.objects.filter(status="completed").update(status="enrolled")


def enrolled_to_completed(apps, schema_editor):
    Enrollment = apps.get_model("students", "Enrollment")
    Enrollment.objects.filter(status="enrolled").update(status="completed")


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0004_studentguardian_id_number"),
    ]

    operations = [
        migrations.RunPython(completed_to_enrolled, enrolled_to_completed),
    ]

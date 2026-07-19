from django.db import migrations


def normalize_score_condition_status(apps, schema_editor):
    Grade = apps.get_model("grading", "Grade")
    Grade.objects.filter(condition_status="score").update(condition_status="graded")


def noop_reverse(apps, schema_editor):
    # Irreversible normalization: keep canonical enum value.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("grading", "0007_grade_conditions"),
    ]

    operations = [
        migrations.RunPython(normalize_score_condition_status, noop_reverse),
    ]

from django.db import migrations


def normalize_grade_condition_statuses(apps, schema_editor):
    Grade = apps.get_model("grading", "Grade")

    # Alias used by older clients.
    Grade.objects.filter(condition_status="score").update(condition_status="graded")

    # Legacy statuses consolidated into the new explicit no_grade condition.
    Grade.objects.filter(
        condition_status__in=["missing", "excused", "absent", "not_submitted", "withdrawn"]
    ).update(condition_status="no_grade")

    # Legacy no-grade representation: pending + reason=no_grade.
    Grade.objects.filter(condition_status="pending", condition_reason="no_grade").update(
        condition_status="no_grade",
        condition_reason=None,
    )


def noop_reverse(apps, schema_editor):
    # Irreversible normalization: keep canonical enum values.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("grading", "0008_normalize_score_condition_status"),
    ]

    operations = [
        migrations.RunPython(normalize_grade_condition_statuses, noop_reverse),
    ]

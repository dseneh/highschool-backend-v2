from django.db import migrations, models


def backfill_grade_conditions(apps, schema_editor):
    Grade = apps.get_model("grading", "Grade")
    Grade.objects.filter(score__isnull=False).update(condition_status="graded")
    Grade.objects.filter(score__isnull=True).update(condition_status="pending")


class Migration(migrations.Migration):
    dependencies = [
        ("grading", "0006_transcript_access"),
    ]

    operations = [
        migrations.AddField(
            model_name="grade",
            name="condition_status",
            field=models.CharField(
                choices=[
                    ("graded", "Graded"),
                    ("missing", "Missing"),
                    ("incomplete", "Incomplete"),
                    ("excused", "Excused"),
                    ("absent", "Absent"),
                    ("not_submitted", "Not Submitted"),
                    ("pending", "Pending"),
                    ("exempt", "Exempt"),
                    ("withdrawn", "Withdrawn"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="grade",
            name="condition_reason",
            field=models.TextField(blank=True, default=None, null=True),
        ),
        migrations.RunPython(backfill_grade_conditions, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="grade",
            index=models.Index(fields=["student", "condition_status"], name="grade_student_cond_idx"),
        ),
        migrations.AddIndex(
            model_name="grade",
            index=models.Index(fields=["assessment", "condition_status"], name="grade_assess_cond_idx"),
        ),
        migrations.AddConstraint(
            model_name="grade",
            constraint=models.CheckConstraint(
                check=models.Q(condition_status="graded", score__isnull=False)
                | ~models.Q(condition_status="graded"),
                name="grade_graded_condition_requires_score",
            ),
        ),
        migrations.AddConstraint(
            model_name="grade",
            constraint=models.CheckConstraint(
                check=models.Q(condition_status="graded") | models.Q(score__isnull=True),
                name="grade_non_graded_condition_requires_null_score",
            ),
        ),
    ]

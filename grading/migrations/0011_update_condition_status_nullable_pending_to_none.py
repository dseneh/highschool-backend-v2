# Generated migration to make condition_status nullable and convert PENDING to None

from django.db import migrations, models


def convert_pending_to_none(apps, schema_editor):
    """Convert all PENDING condition_status values to None."""
    Grade = apps.get_model('grading', 'Grade')
    Grade.objects.filter(condition_status='pending').update(condition_status=None)


def reverse_none_to_pending(apps, schema_editor):
    """Reverse operation: convert None back to PENDING."""
    Grade = apps.get_model('grading', 'Grade')
    Grade.objects.filter(condition_status__isnull=True).update(condition_status='pending')


class Migration(migrations.Migration):
    dependencies = [
        ("grading", "0010_merge_20260719_2003"),
    ]

    operations = [
        # First, alter the field to be nullable with default=None
        # This allows the field to accept NULL values
        migrations.AlterField(
            model_name="grade",
            name="condition_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("graded", "Graded"),
                    ("no_grade", "No Grade"),
                    ("incomplete", "Incomplete"),
                    ("pending", "Pending"),
                    ("exempt", "Exempt"),
                ],
                db_index=True,
                default=None,
                max_length=20,
                null=True,
            ),
        ),
        
        # Then run the data migration to convert PENDING to None
        migrations.RunPython(convert_pending_to_none, reverse_none_to_pending),
    ]


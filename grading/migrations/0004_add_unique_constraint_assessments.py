# Add unique constraint to prevent duplicate assessments
# This runs AFTER the duplicate removal migration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grading', '0003_remove_duplicate_assessments'),
    ]

    operations = [
        # Add unique constraint to prevent duplicate assessments with same
        # (gradebook, marking_period, assessment_type) combination
        # This is especially important for single-entry assessments to ensure
        # only ONE final grade assessment per marking period
        migrations.AddConstraint(
            model_name='assessment',
            constraint=models.UniqueConstraint(
                fields=['gradebook', 'marking_period', 'assessment_type'],
                name='unique_assessment_per_mp_and_type',
            ),
        ),
    ]

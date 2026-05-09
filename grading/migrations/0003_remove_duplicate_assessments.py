# Data cleanup migration to remove duplicate assessments
# This must run BEFORE the unique constraint migration

from django.db import migrations


def remove_duplicate_assessments(apps, schema_editor):
    """
    Remove duplicate assessments keeping only the oldest one.
    
    For each (gradebook, marking_period, assessment_type) combination,
    keep only the first (oldest) assessment and delete the rest.
    """
    Assessment = apps.get_model('grading', 'Assessment')
    
    # Get all duplicate combinations
    from django.db.models import Count
    duplicates = (
        Assessment.objects
        .values('gradebook_id', 'marking_period_id', 'assessment_type_id')
        .annotate(count=Count('id'))
        .filter(count__gt=1)
    )
    
    deleted_count = 0
    for dup in duplicates:
        # Get all assessments for this combination, ordered by creation date
        assessments = Assessment.objects.filter(
            gradebook_id=dup['gradebook_id'],
            marking_period_id=dup['marking_period_id'],
            assessment_type_id=dup['assessment_type_id']
        ).order_by('created_at')
        
        # Keep the first (oldest) one, delete the rest
        to_delete = assessments[1:]
        deleted = len(to_delete)
        
        # Delete associated grades first (due to foreign key constraint)
        from django.db import connection
        cursor = connection.cursor()
        for assessment in to_delete:
            # Delete grades for this assessment
            assessment.grades.all().delete()
            # Delete the assessment
            assessment.delete()
            deleted_count += 1
        
        if deleted > 0:
            print(f"Removed {deleted} duplicate assessment(s) for "
                  f"gradebook={dup['gradebook_id']}, "
                  f"marking_period={dup['marking_period_id']}, "
                  f"assessment_type={dup['assessment_type_id']}")
    
    if deleted_count == 0:
        print("No duplicate assessments found to remove")
    else:
        print(f"Total: Removed {deleted_count} duplicate assessments and their grades")


def reverse_cleanup(apps, schema_editor):
    """
    This is a data cleanup migration, so we cannot reverse it.
    If needed, restore from backup.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('grading', '0002_initial'),
    ]

    operations = [
        migrations.RunPython(remove_duplicate_assessments, reverse_cleanup),
    ]

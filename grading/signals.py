"""
Grade change tracking signals.

Automatically logs grade changes to GradeHistory for audit trail.
"""

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from grading.models import Grade, GradeHistory


@receiver(pre_save, sender=Grade)
def capture_grade_changes(sender, instance, **kwargs):
    """Capture old values before save"""
    if instance.pk:
        try:
            old_grade = Grade.objects.get(pk=instance.pk)
            # Store old values temporarily on instance
            instance._old_score = old_grade.score
            instance._old_status = old_grade.status
            instance._old_comment = old_grade.comment
        except Grade.DoesNotExist:
            pass


@receiver(post_save, sender=Grade)
def log_grade_history(sender, instance, created, **kwargs):
    """Create history record after save"""
    if created:
        # New grade created
        GradeHistory.objects.create(
            grade=instance,
            new_score=instance.score,
            new_status=instance.status,
            new_comment=instance.comment,
            changed_by=instance.updated_by,
            change_type="create"
        )
    else:
        # Grade updated - check what changed
        change_type = "score"
        should_log = False

        old_score = getattr(instance, '_old_score', None)
        old_status = getattr(instance, '_old_status', None)
        old_comment = getattr(instance, '_old_comment', None)

        if old_score != instance.score:
            change_type = "score"
            should_log = True

        if old_status != instance.status:
            change_type = "status"
            should_log = True

        if old_comment != instance.comment:
            if not should_log or change_type == "score":
                change_type = "comment"
            should_log = True

        if should_log:
            GradeHistory.objects.create(
                grade=instance,
                old_score=old_score,
                new_score=instance.score,
                old_status=old_status,
                new_status=instance.status,
                old_comment=old_comment,
                new_comment=instance.comment,
                changed_by=instance.updated_by,
                change_type=change_type
            )

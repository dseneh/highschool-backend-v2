import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from finance.models import PaymentInstallment, Transaction
from finance.views.payment_installment import (
    clear_installment_cache,
    clear_student_payment_cache,
)

logger = logging.getLogger(__name__)

# Import StudentEnrollmentBill here to avoid circular imports
# We'll import it inside the signal handler


@receiver(post_save, sender=PaymentInstallment)
def invalidate_installment_cache_on_save(sender, instance, created, **kwargs):
    """
    Clear installment cache when a PaymentInstallment is created or updated.
    Also invalidates payment_status and payment_plan caches for all enrollments
    in that academic year, and queues background task to recalculate all
    StudentPaymentSummary records (affects all students, so async).

    This ensures cache is invalidated even when records are modified outside the API
    (e.g., Django admin, direct model saves, bulk updates).

    Note: next_due_date is calculated dynamically and not cached, so it will be
    automatically recalculated on next access after cache invalidation.
    """
    try:
        academic_year_id = instance.academic_year.id if instance.academic_year else None
        installment_id = instance.id

        logger.info(
            f"Invalidating installment cache for {'created' if created else 'updated'} "
            f"installment {installment_id} (academic_year: {academic_year_id})"
        )

        # Clear installment-specific caches and payment_status/payment_plan caches
        # This clears Redis cache for payment_status which includes next_due_date calculation
        # IMPORTANT: This must be called even for updates to ensure cache is invalidated
        clear_installment_cache(
            academic_year_id=academic_year_id,
            installment_ids=[installment_id],
        )

        logger.debug(
            f"Cache cleared for installment {installment_id}. "
            f"Payment status caches for academic_year {academic_year_id} will be recalculated."
        )

        # Queue background task to recalculate all payment summaries for this academic year
        # (affects all students, so async to avoid blocking API response)
        # This updates StudentPaymentSummary table (payment_status without next_due_date)
        if academic_year_id:
            try:
                from students.models import Enrollment
                from finance.tasks import (
                    recalc_payment_summaries_async,
                    recalc_payment_summaries_for_academic_year,
                )

                # Check enrollment count - if small (< 50), do it synchronously for immediate update
                enrollment_count = Enrollment.objects.filter(
                    academic_year_id=academic_year_id, status="active"
                ).count()

                if enrollment_count < 50:
                    # Small dataset - update synchronously for immediate effect
                    logger.info(
                        f"Updating payment summaries synchronously for academic year "
                        f"{academic_year_id} ({enrollment_count} enrollments)"
                    )
                    recalc_payment_summaries_for_academic_year(academic_year_id)
                else:
                    # Large dataset - update asynchronously
                    recalc_payment_summaries_async(academic_year_id)
                    logger.info(
                        f"Queued background task to recalculate payment summaries "
                        f"for academic year {academic_year_id} ({enrollment_count} enrollments)"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to recalculate payment summaries for "
                    f"academic year {academic_year_id}: {e}",
                    exc_info=True,
                )
    except Exception as e:
        logger.error(f"Error invalidating installment cache on save: {e}")
        # Don't fail the save operation if cache clearing fails


@receiver(post_delete, sender=PaymentInstallment)
def invalidate_installment_cache_on_delete(sender, instance, **kwargs):
    """
    Clear installment cache when a PaymentInstallment is deleted.
    Also queues background task to recalculate all StudentPaymentSummary records
    for that academic year (affects all students, so async).
    This ensures cache is invalidated even when records are deleted outside the API.
    """
    try:
        # Get IDs before deletion (instance still has them)
        academic_year_id = instance.academic_year.id if instance.academic_year else None
        installment_id = instance.id

        logger.info(
            f"Invalidating installment cache for deleted "
            f"installment {installment_id} (academic_year: {academic_year_id})"
        )

        clear_installment_cache(
            academic_year_id=academic_year_id,
            installment_ids=[installment_id],
        )

        # Queue background task to recalculate all payment summaries for this academic year
        if academic_year_id:
            try:
                from students.models import Enrollment
                from finance.tasks import (
                    recalc_payment_summaries_async,
                    recalc_payment_summaries_for_academic_year,
                )

                # Check enrollment count - if small (< 50), do it synchronously for immediate update
                enrollment_count = Enrollment.objects.filter(
                    academic_year_id=academic_year_id, status="active"
                ).count()

                if enrollment_count < 50:
                    # Small dataset - update synchronously for immediate effect
                    logger.info(
                        f"Updating payment summaries synchronously for academic year "
                        f"{academic_year_id} ({enrollment_count} enrollments)"
                    )
                    recalc_payment_summaries_for_academic_year(academic_year_id)
                else:
                    # Large dataset - update asynchronously
                    recalc_payment_summaries_async(academic_year_id)
                    logger.info(
                        f"Queued background task to recalculate payment summaries "
                        f"for academic year {academic_year_id} ({enrollment_count} enrollments)"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to recalculate payment summaries for "
                    f"academic year {academic_year_id}: {e}",
                    exc_info=True,
                )
    except Exception as e:
        logger.error(f"Error invalidating installment cache on delete: {e}")
        # Don't fail the delete operation if cache clearing fails


# ========================================
# TRANSACTION CACHE INVALIDATION SIGNALS
# ========================================


@receiver(post_save, sender=Transaction)
def invalidate_payment_cache_on_transaction_save(sender, instance, created, **kwargs):
    """
    Clear payment plan and payment status caches when a Transaction is created or updated.
    Also updates StudentPaymentSummary table synchronously.
    This ensures payment data stays in sync when payments are posted.
    """
    try:
        # Only invalidate if transaction affects student payments
        if not instance.student or not instance.academic_year:
            return

        # Get all active enrollments for this student in this academic year
        enrollments = instance.student.enrollments.filter(
            academic_year=instance.academic_year, status="active"
        )

        academic_year_id = instance.academic_year.id

        # Clear cache and update summary table for each enrollment
        for enrollment in enrollments:
            clear_student_payment_cache(
                enrollment_id=enrollment.id,
                academic_year_id=academic_year_id,
            )

            # Update StudentPaymentSummary synchronously (affects single student, fast)
            try:
                from finance.utils import calculate_student_payment_summary

                calculate_student_payment_summary(enrollment, instance.academic_year)
            except Exception as e:
                logger.warning(
                    f"Failed to update payment summary for enrollment {enrollment.id}: {e}"
                )

        logger.info(
            f"Invalidated payment cache for {'created' if created else 'updated'} "
            f"transaction {instance.id} (student: {instance.student.id}, "
            f"academic_year: {academic_year_id}, enrollments: {enrollments.count()})"
        )
    except Exception as e:
        logger.error(f"Error invalidating payment cache on transaction save: {e}")
        # Don't fail the save operation if cache clearing fails


@receiver(post_delete, sender=Transaction)
def invalidate_payment_cache_on_transaction_delete(sender, instance, **kwargs):
    """
    Clear payment plan and payment status caches when a Transaction is deleted.
    Also updates StudentPaymentSummary table synchronously.
    This ensures payment data stays in sync when payments are removed.
    """
    try:
        # Only invalidate if transaction affects student payments
        if not instance.student or not instance.academic_year:
            return

        # Get all active enrollments for this student in this academic year
        enrollments = instance.student.enrollments.filter(
            academic_year=instance.academic_year, status="active"
        )

        academic_year_id = instance.academic_year.id

        # Clear cache and update summary table for each enrollment
        for enrollment in enrollments:
            clear_student_payment_cache(
                enrollment_id=enrollment.id,
                academic_year_id=academic_year_id,
            )

            # Update StudentPaymentSummary synchronously (affects single student, fast)
            try:
                from finance.utils import calculate_student_payment_summary

                calculate_student_payment_summary(enrollment, instance.academic_year)
            except Exception as e:
                logger.warning(
                    f"Failed to update payment summary for enrollment {enrollment.id}: {e}"
                )

        logger.info(
            f"Invalidated payment cache for deleted transaction {instance.id} "
            f"(student: {instance.student.id}, academic_year: {academic_year_id}, "
            f"enrollments: {enrollments.count()})"
        )
    except Exception as e:
        logger.error(f"Error invalidating payment cache on transaction delete: {e}")
        # Don't fail the delete operation if cache clearing fails


# ========================================
# STUDENT BILL CACHE INVALIDATION SIGNALS
# ========================================


@receiver(post_save, sender="students.StudentEnrollmentBill")
def invalidate_payment_cache_on_bill_save(sender, instance, created, **kwargs):
    """
    Clear payment plan and payment status caches when a StudentEnrollmentBill is created or updated.
    Also updates StudentPaymentSummary table synchronously.
    This ensures payment plans stay in sync when bills change (affects total_bills calculation).
    """
    try:
        enrollment = instance.enrollment
        if not enrollment or not enrollment.academic_year:
            return

        academic_year_id = enrollment.academic_year.id

        # Clear cache for this enrollment
        clear_student_payment_cache(
            enrollment_id=enrollment.id,
            academic_year_id=academic_year_id,
        )

        # Update StudentPaymentSummary synchronously (affects single student, fast)
        try:
            from finance.utils import calculate_student_payment_summary

            calculate_student_payment_summary(enrollment, enrollment.academic_year)
        except Exception as e:
            logger.warning(
                f"Failed to update payment summary for enrollment {enrollment.id}: {e}"
            )

        logger.info(
            f"Invalidated payment cache for {'created' if created else 'updated'} "
            f"bill {instance.id} (enrollment: {enrollment.id}, academic_year: {academic_year_id})"
        )
    except Exception as e:
        logger.error(f"Error invalidating payment cache on bill save: {e}")
        # Don't fail the save operation if cache clearing fails


@receiver(post_delete, sender="students.StudentEnrollmentBill")
def invalidate_payment_cache_on_bill_delete(sender, instance, **kwargs):
    """
    Clear payment plan and payment status caches when a StudentEnrollmentBill is deleted.
    Also updates StudentPaymentSummary table synchronously.
    This ensures payment plans stay in sync when bills are removed.
    """
    try:
        # Get enrollment before deletion (instance still has it)
        enrollment = instance.enrollment
        if not enrollment or not enrollment.academic_year:
            return

        academic_year_id = enrollment.academic_year.id

        # Clear cache for this enrollment
        clear_student_payment_cache(
            enrollment_id=enrollment.id,
            academic_year_id=academic_year_id,
        )

        # Update StudentPaymentSummary synchronously (affects single student, fast)
        try:
            from finance.utils import calculate_student_payment_summary

            calculate_student_payment_summary(enrollment, enrollment.academic_year)
        except Exception as e:
            logger.warning(
                f"Failed to update payment summary for enrollment {enrollment.id}: {e}"
            )

        logger.info(
            f"Invalidated payment cache for deleted bill {instance.id} "
            f"(enrollment: {enrollment.id}, academic_year: {academic_year_id})"
        )
    except Exception as e:
        logger.error(f"Error invalidating payment cache on bill delete: {e}")
        # Don't fail the delete operation if cache clearing fails


# ========================================
# STUDENT CONCESSION CACHE INVALIDATION SIGNALS
# ========================================


@receiver(post_save, sender="students.StudentConcession")
def invalidate_payment_cache_on_concession_save(sender, instance, created, **kwargs):
    """
    Clear payment plan and payment status caches when a StudentConcession is created or updated.
    Also updates StudentPaymentSummary table synchronously.
    This ensures payment plans stay in sync when concessions change (affects net total calculation).
    """
    try:
        # Get enrollment from student + academic_year (StudentConcession doesn't have enrollment field)
        enrollment = instance.student.enrollments.filter(
            academic_year=instance.academic_year
        ).first()
        
        if not enrollment:
            logger.warning(
                f"No enrollment found for concession {instance.id} "
                f"(student: {instance.student.id}, academic_year: {instance.academic_year.id})"
            )
            return

        academic_year_id = instance.academic_year.id

        # Clear cache for this enrollment
        clear_student_payment_cache(
            enrollment_id=enrollment.id,
            academic_year_id=academic_year_id,
        )

        # Update StudentPaymentSummary synchronously (affects single student, fast)
        try:
            from finance.utils import calculate_student_payment_summary

            calculate_student_payment_summary(enrollment, enrollment.academic_year)
        except Exception as e:
            logger.warning(
                f"Failed to update payment summary for enrollment {enrollment.id}: {e}"
            )

        logger.info(
            f"Invalidated payment cache for {'created' if created else 'updated'} "
            f"concession {instance.id} (enrollment: {enrollment.id}, academic_year: {academic_year_id})"
        )
    except Exception as e:
        logger.error(f"Error invalidating payment cache on concession save: {e}")
        # Don't fail the save operation if cache clearing fails


@receiver(post_delete, sender="students.StudentConcession")
def invalidate_payment_cache_on_concession_delete(sender, instance, **kwargs):
    """
    Clear payment plan and payment status caches when a StudentConcession is deleted.
    Also updates StudentPaymentSummary table synchronously.
    This ensures payment plans stay in sync when concessions are removed.
    """
    try:
        # Get enrollment from student + academic_year (StudentConcession doesn't have enrollment field)
        enrollment = instance.student.enrollments.filter(
            academic_year=instance.academic_year
        ).first()
        
        if not enrollment:
            logger.warning(
                f"No enrollment found for deleted concession {instance.id} "
                f"(student: {instance.student.id}, academic_year: {instance.academic_year.id})"
            )
            return

        academic_year_id = instance.academic_year.id

        # Clear cache for this enrollment
        clear_student_payment_cache(
            enrollment_id=enrollment.id,
            academic_year_id=academic_year_id,
        )

        # Update StudentPaymentSummary synchronously (affects single student, fast)
        try:
            from finance.utils import calculate_student_payment_summary

            calculate_student_payment_summary(enrollment, enrollment.academic_year)
        except Exception as e:
            logger.warning(
                f"Failed to update payment summary for enrollment {enrollment.id}: {e}"
            )

        logger.info(
            f"Invalidated payment cache for deleted concession {instance.id} "
            f"(enrollment: {enrollment.id}, academic_year: {academic_year_id})"
        )
    except Exception as e:
        logger.error(f"Error invalidating payment cache on concession delete: {e}")
        # Don't fail the delete operation if cache clearing fails

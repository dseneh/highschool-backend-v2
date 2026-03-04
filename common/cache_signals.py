"""
Signal handlers for automatic cache invalidation when reference data changes.

These signals ensure that cached reference data is always up-to-date by
invalidating the cache whenever the underlying models are modified.
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import logging

from common.cache_service import DataCache

logger = logging.getLogger(__name__)


# ==================== DIVISION SIGNALS ====================

@receiver([post_save, post_delete], sender='academics.Division')
def invalidate_division_cache(sender, instance, **kwargs):
    """Invalidate division cache when a division is saved or deleted."""
    try:
        request = kwargs.get("request")
        DataCache.invalidate_divisions(request)
    except Exception as e:
        logger.error(f"Error invalidating division cache: {e}")


# ==================== GRADE LEVEL SIGNALS ====================

@receiver([post_save, post_delete], sender='academics.GradeLevel')
def invalidate_grade_level_cache(sender, instance, **kwargs):
    """Invalidate grade level cache when a grade level is saved or deleted."""
    try:
        request = kwargs.get("request")
        DataCache.invalidate_grade_levels(request)
    except Exception as e:
        logger.error(f"Error invalidating grade level cache: {e}")


# ==================== SECTION SIGNALS ====================

@receiver([post_save, post_delete], sender='academics.Section')
def invalidate_section_cache(sender, instance, **kwargs):
    """Invalidate section cache when a section is saved or deleted."""
    try:
        request = kwargs.get("request")
        DataCache.invalidate_sections(request)
    except Exception as e:
        logger.error(f"Error invalidating section cache: {e}")


# ==================== ACADEMIC YEAR SIGNALS ====================

@receiver([post_save, post_delete], sender='academics.AcademicYear')
def invalidate_academic_year_cache(sender, instance, **kwargs):
    """Invalidate academic year cache when an academic year is saved or deleted."""
    try:
        request = kwargs.get("request")
        DataCache.invalidate_academic_years(request)
        
        # Also invalidate related data that might be filtered by academic year
        DataCache.invalidate_sections(request)
        DataCache.invalidate_semesters(request)
        DataCache.invalidate_installments(request)
    except Exception as e:
        logger.error(f"Error invalidating academic year cache: {e}")


# ==================== SEMESTER SIGNALS ====================

@receiver([post_save, post_delete], sender='academics.Semester')
def invalidate_semester_cache(sender, instance, **kwargs):
    """Invalidate semester cache when a semester is saved or deleted."""
    try:
        request = kwargs.get("request")
        DataCache.invalidate_semesters(request)
        
        # Also invalidate marking periods since they depend on semesters
        DataCache.invalidate_marking_periods(request)
    except Exception as e:
        logger.error(f"Error invalidating semester cache: {e}")


# ==================== MARKING PERIOD SIGNALS ====================

@receiver([post_save, post_delete], sender='academics.MarkingPeriod')
def invalidate_marking_period_cache(sender, instance, **kwargs):
    """Invalidate marking period cache when a marking period is saved or deleted."""
    try:
        request = kwargs.get("request")
        DataCache.invalidate_marking_periods(request)
    except Exception as e:
        logger.error(f"Error invalidating marking period cache: {e}")


# ==================== SUBJECT SIGNALS ====================

@receiver([post_save, post_delete], sender='academics.Subject')
def invalidate_subject_cache(sender, instance, **kwargs):
    """Invalidate subject cache when a subject is saved or deleted."""
    try:
        request = kwargs.get("request")
        DataCache.invalidate_subjects(request)
    except Exception as e:
        logger.error(f"Error invalidating subject cache: {e}")


# ==================== PAYMENT METHOD SIGNALS ====================

@receiver([post_save, post_delete], sender='finance.PaymentMethod')
def invalidate_payment_method_cache(sender, instance, **kwargs):
    """Invalidate payment method cache when a payment method is saved or deleted."""
    try:
        request = kwargs.get("request")
        DataCache.invalidate_payment_methods(request)
    except Exception as e:
        logger.error(f"Error invalidating payment method cache: {e}")


# ==================== TRANSACTION TYPE SIGNALS ====================

@receiver([post_save, post_delete], sender='finance.TransactionType')
def invalidate_transaction_type_cache(sender, instance, **kwargs):
    """Invalidate transaction type cache when a transaction type is saved or deleted."""
    try:
        request = kwargs.get("request")
        DataCache.invalidate_transaction_types(request)
    except Exception as e:
        logger.error(f"Error invalidating transaction type cache: {e}")


# ==================== INSTALLMENT SIGNALS ====================

@receiver([post_save, post_delete], sender='finance.PaymentInstallment')
def invalidate_installment_cache(sender, instance, **kwargs):
    """Invalidate installment cache when an installment is saved or deleted."""
    try:
        request = kwargs.get("request")
        academic_year_id = str(instance.academic_year_id) if instance.academic_year_id else None
        DataCache.invalidate_installments(request, academic_year_id)
    except Exception as e:
        logger.error(f"Error invalidating installment cache: {e}")


# ==================== SCHOOL SIGNALS ====================

@receiver([post_save, post_delete], sender='core.Tenant')
def invalidate_school_cache(sender, instance, **kwargs):
    """
    Invalidate ALL reference data caches for a school when the school is modified.
    This is a safety net to ensure data consistency.
    """
    try:
        request = kwargs.get("request")
        # For school updates, we might want to invalidate everything
        # but only on delete or significant changes
        if kwargs.get('signal') == post_delete:
            DataCache.invalidate_all(request)
    except Exception as e:
        logger.error(f"Error invalidating school cache: {e}")

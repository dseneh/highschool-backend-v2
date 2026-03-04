"""
Settings Django Adapter - Database Operations

This module handles all Django-specific database operations for settings.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional
from django.db import transaction
from django.db.models import Q

from settings.models import GradingSettings
from business.settings.settings_models import GradingSettingsData


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_settings_to_data(settings) -> GradingSettingsData:
    """Convert Django GradingSettings model to business data object"""
    return GradingSettingsData(
        id=str(settings.id),
        grading_style=settings.grading_style,
        single_entry_assessment_name=settings.single_entry_assessment_name,
        use_default_templates=settings.use_default_templates,
        auto_calculate_final_grade=settings.auto_calculate_final_grade,
        default_calculation_method=settings.default_calculation_method,
        require_grade_approval=settings.require_grade_approval,
        require_grade_review=settings.require_grade_review,
        display_assessment_on_single_entry=settings.display_assessment_on_single_entry,
        allow_assessment_delete=settings.allow_assessment_delete,
        allow_assessment_create=settings.allow_assessment_create,
        allow_assessment_edit=settings.allow_assessment_edit,
        use_letter_grades=settings.use_letter_grades,
        allow_teacher_override=settings.allow_teacher_override,
        lock_grades_after_semester=settings.lock_grades_after_semester,
        display_grade_status=settings.display_grade_status,
        cumulative_average_calculation=settings.cumulative_average_calculation,
        notes=settings.notes or "",
    )

@transaction.atomic
def create_settings_in_db(data: dict, user=None) -> Optional[GradingSettings]:
    """
    Create grading settings in database
    
    Args:
        data: Prepared settings data
        user: User creating the settings
        
    Returns:
        Created GradingSettings instance or None if failed
    """
    try:
        
        settings = GradingSettings.objects.create(
            grading_style=data.get('grading_style', 'multiple_entry'),
            single_entry_assessment_name=data.get('single_entry_assessment_name', 'Final Grade'),
            use_default_templates=data.get('use_default_templates', True),
            auto_calculate_final_grade=data.get('auto_calculate_final_grade', True),
            default_calculation_method=data.get('default_calculation_method', 'average'),
            require_grade_approval=data.get('require_grade_approval', True),
            require_grade_review=data.get('require_grade_review', True),
            display_assessment_on_single_entry=data.get('display_assessment_on_single_entry', True),
            allow_assessment_delete=data.get('allow_assessment_delete', False),
            allow_assessment_create=data.get('allow_assessment_create', False),
            allow_assessment_edit=data.get('allow_assessment_edit', False),
            use_letter_grades=data.get('use_letter_grades', True),
            allow_teacher_override=data.get('allow_teacher_override', True),
            lock_grades_after_semester=data.get('lock_grades_after_semester', False),
            display_grade_status=data.get('display_grade_status', True),
            cumulative_average_calculation=data.get('cumulative_average_calculation', False),
            notes=data.get('notes', ''),
            created_by=user,
            updated_by=user,
        )
        
        return settings
    except Exception:
        return None


@transaction.atomic
def get_or_create_settings_in_db(user=None) -> tuple[GradingSettings, bool]:
    """
    Get or create grading settings
    
    Args:
        user: User creating the settings (if new)
        
    Returns:
        Tuple of (settings, created)
    """
    try:
        
        settings, created = GradingSettings.objects.get_or_create(
            defaults={
                'created_by': user,
                'updated_by': user,
            }
        )
        
        if not created and user:
            settings.updated_by = user
            settings.save(update_fields=['updated_by', 'updated_at'])
        
        return settings, created
    except Exception:
        return None, False


@transaction.atomic
def update_settings_in_db(data: dict, user=None) -> Optional[GradingSettings]:
    """
    Update grading settings in database
    
    Args:
        data: Update data dictionary
        user: User updating the settings
        
    Returns:
        Updated GradingSettings instance or None if not found
    """
    try:
        settings = GradingSettings.objects.first()
        
        for field, value in data.items():
            if hasattr(settings, field) and field not in ['id','created_at', 'created_by']:
                setattr(settings, field, value)
        
        settings.updated_by = user
        settings.save()
        
        return settings
    except GradingSettings.DoesNotExist:
        return None


def delete_settings_from_db() -> bool:
    """
    Delete grading settings from database
        
    Returns:
        True if deleted, False if not found
    """
    try:
        GradingSettings.objects.first().delete()
        return True
    except GradingSettings.DoesNotExist:
        return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def settings_exist() -> bool:
    """Check if grading settings exist"""
    return GradingSettings.objects.exists()


def get_current_grading_style() -> Optional[str]:
    """Get current grading style for a school"""
    try:
        settings = GradingSettings.objects.first()
        return settings.grading_style
    except GradingSettings.DoesNotExist:
        return None


def bulk_create_default_settings(user=None) -> list:
    """
    Create default settings for multiple schools
    
    Args:
        user: User creating the settings
        
    Returns:
        List of created GradingSettings instances
    """
    settings_list = []
    
    if not settings_exist():
        settings = create_settings_in_db({}, user)
        if settings:
            settings_list.append(settings)
    
    return settings_list

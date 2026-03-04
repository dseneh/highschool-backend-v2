"""
Settings Service - Pure Business Logic

This module contains all business logic for system settings validation.
NO Django dependencies - only pure Python validation and business rules.
"""

from typing import Optional, Tuple


def validate_grading_style(style: str) -> Optional[str]:
    """
    Validate grading style value
    
    Args:
        style: Grading style ('single_entry' or 'multiple_entry')
        
    Returns:
        Error message or None if valid
    """
    valid_styles = ['single_entry', 'multiple_entry']
    
    if style not in valid_styles:
        return f"Invalid grading style. Must be one of: {', '.join(valid_styles)}"
    
    return None


def validate_calculation_method(method: str) -> Optional[str]:
    """
    Validate calculation method
    
    Args:
        method: Calculation method ('average' or 'weighted')
        
    Returns:
        Error message or None if valid
    """
    valid_methods = ['average', 'weighted']
    
    if method not in valid_methods:
        return f"Invalid calculation method. Must be one of: {', '.join(valid_methods)}"
    
    return None


def validate_grading_settings_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate grading settings data
    
    Args:
        data: Settings data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    validated_data = {}
    
    # Validate grading style if provided
    if 'grading_style' in data:
        style_error = validate_grading_style(data['grading_style'])
        if style_error:
            return None, style_error
        validated_data['grading_style'] = data['grading_style']
    
    # Validate calculation method if provided
    if 'default_calculation_method' in data:
        method_error = validate_calculation_method(data['default_calculation_method'])
        if method_error:
            return None, method_error
        validated_data['default_calculation_method'] = data['default_calculation_method']
    
    # Copy other allowed fields
    allowed_fields = [
        'single_entry_assessment_name',
        'use_default_templates',
        'auto_calculate_final_grade',
        'require_grade_approval',
        'require_grade_review',
        'display_assessment_on_single_entry',
        'allow_assessment_delete',
        'allow_assessment_create',
        'allow_assessment_edit',
        'use_letter_grades',
        'allow_teacher_override',
        'lock_grades_after_semester',
        'display_grade_status',
        'cumulative_average_calculation',
        'notes',
    ]
    
    for field in allowed_fields:
        if field in data:
            validated_data[field] = data[field]
    
    return validated_data, None


# =============================================================================
# BUSINESS LOGIC FUNCTIONS
# =============================================================================

def is_single_entry_mode(grading_style: str) -> bool:
    """
    Check if grading style is single entry
    
    Args:
        grading_style: Grading style value
        
    Returns:
        True if single entry mode
    """
    return grading_style == 'single_entry'


def is_multiple_entry_mode(grading_style: str) -> bool:
    """
    Check if grading style is multiple entry
    
    Args:
        grading_style: Grading style value
        
    Returns:
        True if multiple entry mode
    """
    return grading_style == 'multiple_entry'


def should_use_templates(grading_style: str, use_templates: bool) -> bool:
    """
    Determine if default templates should be used
    
    Args:
        grading_style: Grading style value
        use_templates: User preference for using templates
        
    Returns:
        True if templates should be used
    """
    # Single entry mode never uses templates
    if is_single_entry_mode(grading_style):
        return False
    
    return use_templates


def requires_gradebook_reinitialization(old_style: str, new_style: str) -> bool:
    """
    Check if grading style change requires gradebook reinitialization
    
    Args:
        old_style: Current grading style
        new_style: New grading style
        
    Returns:
        True if reinitialization is required
    """
    return old_style != new_style


def prepare_settings_for_save(data: dict, grading_style: str) -> dict:
    """
    Prepare settings data for saving, applying business rules
    
    Args:
        data: Validated settings data
        grading_style: Grading style (from data or existing)
        
    Returns:
        Prepared data dictionary with business rules applied
    """
    prepared = data.copy()
    
    # If single entry mode, disable template usage
    if is_single_entry_mode(grading_style):
        prepared['use_default_templates'] = False
    
    return prepared


def get_settings_change_warnings(old_style: str, new_style: str) -> list:
    """
    Get warnings for settings changes
    
    Args:
        old_style: Current grading style
        new_style: New grading style
        
    Returns:
        List of warning messages
    """
    warnings = []
    
    if requires_gradebook_reinitialization(old_style, new_style):
        warnings.extend([
            "This operation will DELETE all existing gradebooks, assessments, and grades!",
            "All grading data will be permanently lost.",
            "This action cannot be undone.",
            'Pass "force": true to confirm and proceed with reinitialization',
        ])
    
    return warnings


def validate_settings_consistency(data: dict) -> Optional[str]:
    """
    Validate consistency of settings combinations
    
    Args:
        data: Settings data dictionary
        
    Returns:
        Error message or None if valid
    """
    # Check for conflicting settings
    grading_style = data.get('grading_style')
    use_templates = data.get('use_default_templates')
    
    # Single entry mode should not use templates
    if grading_style == 'single_entry' and use_templates:
        return "Single entry mode cannot use default templates. This will be automatically disabled."
    
    # If auto-calculate is disabled, template usage may not make sense
    auto_calc = data.get('auto_calculate_final_grade')
    if auto_calc is False and use_templates:
        # This is just a warning, not an error
        pass
    
    return None


def get_default_settings() -> dict:
    """
    Get default grading settings
    
    Returns:
        Dictionary with default settings values
    """
    return {
        'grading_style': 'multiple_entry',
        'single_entry_assessment_name': 'Final Grade',
        'use_default_templates': True,
        'auto_calculate_final_grade': True,
        'default_calculation_method': 'average',
        'require_grade_approval': True,
        'require_grade_review': True,
        'display_assessment_on_single_entry': True,
        'allow_assessment_delete': False,
        'allow_assessment_create': False,
        'allow_assessment_edit': False,
        'use_letter_grades': True,
        'allow_teacher_override': True,
        'lock_grades_after_semester': False,
        'display_grade_status': True,
        'cumulative_average_calculation': False,
        'notes': '',
    }

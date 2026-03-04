"""
Settings Business Logic Module

This module contains all business logic for system settings management.
It is framework-agnostic and contains NO Django dependencies.

Structure:
- services/: Pure Python business logic
- adapters/: Django database operations
- settings_models.py: Data transfer objects (DTOs)

Usage:
    from business.settings.services import validate_grading_settings_data
    from business.settings.adapters import get_settings_by_school
    from business.settings.settings_models import GradingSettingsData
"""

from .settings_models import GradingSettingsData
from .services import (
    validate_grading_style,
    validate_calculation_method,
    validate_grading_settings_data,
    is_single_entry_mode,
    is_multiple_entry_mode,
    should_use_templates,
    requires_gradebook_reinitialization,
    prepare_settings_for_save,
    get_settings_change_warnings,
    validate_settings_consistency,
    get_default_settings,
)

__all__ = [
    # Models
    'GradingSettingsData',
    # Services
    'validate_grading_style',
    'validate_calculation_method',
    'validate_grading_settings_data',
    'is_single_entry_mode',
    'is_multiple_entry_mode',
    'should_use_templates',
    'requires_gradebook_reinitialization',
    'prepare_settings_for_save',
    'get_settings_change_warnings',
    'validate_settings_consistency',
    'get_default_settings',
]

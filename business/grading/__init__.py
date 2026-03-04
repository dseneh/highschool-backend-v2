"""
Grading Business Logic Module

Framework-agnostic business logic for the grading module.
This provides a clean separation between business rules (services)
and database operations (adapters).

Structure:
- services/: Pure Python business logic (validation, calculations, business rules)
- adapters/: Django-specific database operations
- grading_models.py: Data Transfer Objects (DTOs)
"""

from . import services
from . import adapters
from .grading_models import (
    GradeLetterData,
    AssessmentTypeData,
    GradeBookData,
    AssessmentData,
    GradeData,
)

__all__ = [
    'services',
    'adapters',
    'GradeLetterData',
    'AssessmentTypeData',
    'GradeBookData',
    'AssessmentData',
    'GradeData',
]

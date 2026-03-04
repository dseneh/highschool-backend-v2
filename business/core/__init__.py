"""
Core Business Logic Module

Framework-agnostic business logic for core school system entities.
Organized into services (business logic) and adapters (database operations).
"""

# Import from organized folders
from . import services
from . import adapters

# Import data models
from .core_models import (
    SchoolData,
    AcademicYearData,
    SemesterData,
    MarkingPeriodData,
    GradeLevelData,
    SubjectData,
    SectionData,
    DivisionData,
    PeriodData,
)

__all__ = [
    'services',
    'adapters',
    'SchoolData',
    'AcademicYearData',
    'SemesterData',
    'MarkingPeriodData',
    'GradeLevelData',
    'SubjectData',
    'SectionData',
    'DivisionData',
    'PeriodData',
]

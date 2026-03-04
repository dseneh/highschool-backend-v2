"""
Students Business Logic Module

Framework-agnostic business logic for student management.
"""

from . import services
from . import adapters
from .student_models import StudentData

__all__ = ['services', 'adapters', 'StudentData']

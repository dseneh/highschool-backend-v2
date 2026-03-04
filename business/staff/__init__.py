"""
Staff Business Logic Module

Framework-agnostic business logic for staff management.
"""

from . import services
from . import adapters
from .staff_models import StaffData, PositionData, DepartmentData, StaffValidationResult

__all__ = [
    'services',
    'adapters',
    'StaffData',
    'PositionData',
    'DepartmentData',
    'StaffValidationResult',
]

"""
Student data models - Plain Python dataclasses (no Django)
"""
from dataclasses import dataclass
from typing import Optional
from datetime import date


@dataclass
class StudentData:
    """Plain data object for student information"""
    id: Optional[str] = None
    id_number: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    status: Optional[str] = None
    grade_level_id: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    entry_as: Optional[str] = None  # new, returning, transferred
    prev_id_number: Optional[str] = None


@dataclass
class StudentValidationResult:
    """Result of student validation"""
    valid: bool
    errors: list[str]
    warnings: list[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []

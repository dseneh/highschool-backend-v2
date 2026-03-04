"""
Staff Module - Data Transfer Objects (DTOs)

Framework-agnostic data representations for staff management.
No Django or framework-specific imports allowed in this file.
"""

from dataclasses import dataclass
from typing import Optional
from datetime import date


@dataclass
class DepartmentData:
    """Framework-agnostic department data"""
    name: str
    id: str = ""
    code: str = ""
    description: Optional[str] = None


@dataclass
class PositionCategoryData:
    """Framework-agnostic position category data"""
    name: str
    id: str = ""
    description: Optional[str] = None


@dataclass
class PositionData:
    """Framework-agnostic position data"""
    title: str
    id: str = ""
    code: str = ""
    description: Optional[str] = None
    level: int = 1
    employment_type: str = "full_time"  # full_time, part_time, contract, temporary, intern
    compensation_type: str = "salary"  # salary, hourly, stipend
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    teaching_role: bool = False
    can_delete: bool = True
    category_id: Optional[str] = None
    department_id: Optional[str] = None


@dataclass
class StaffData:
    """Framework-agnostic staff data"""
    first_name: str
    last_name: str
    gender: str
    id_number: str
    id: str = ""
    middle_name: str = ""
    date_of_birth: Optional[str] = None  # ISO format: YYYY-MM-DD
    email: Optional[str] = None
    phone_number: str = ""
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    place_of_birth: Optional[str] = None
    status: str = "active"  # active, inactive, suspended, terminated, on_leave, retired
    hire_date: Optional[str] = None  # ISO format: YYYY-MM-DD
    position_id: Optional[str] = None
    primary_department_id: Optional[str] = None
    is_teacher: bool = False
    photo: Optional[str] = None
    suspension_date: Optional[str] = None
    suspension_reason: Optional[str] = None
    termination_date: Optional[str] = None
    termination_reason: Optional[str] = None
    user_account_id_number: Optional[str] = None


@dataclass
class StaffValidationResult:
    """Result of staff validation"""
    is_valid: bool
    errors: list[str]
    warnings: list[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []

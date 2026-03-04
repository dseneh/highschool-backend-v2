"""
Core Module - Data Transfer Objects (DTOs)

Framework-agnostic data representations for core school system entities.
No Django or framework-specific imports allowed in this file.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SchoolData:
    """Framework-agnostic school data"""
    name: str
    country: str
    workspace: str
    id: str = ""
    id_number: str = ""
    short_name: str = ""
    funding_type: str = "private"
    school_type: str = "high school"
    slogan: Optional[str] = None
    emis_number: Optional[str] = None
    description: Optional[str] = None
    date_est: Optional[str] = None  # ISO format: YYYY-MM-DD
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    redirect_url: Optional[str] = None
    status: str = "active"
    logo: Optional[str] = None
    logo_shape: str = "square"
    theme_color: Optional[str] = None


@dataclass
class AcademicYearData:
    """Framework-agnostic academic year data"""
    start_date: str  # ISO format: YYYY-MM-DD
    end_date: str  # ISO format: YYYY-MM-DD
    id: str = ""
    name: str = ""
    current: bool = False
    status: str = "active"


@dataclass
class SemesterData:
    """Framework-agnostic semester data"""
    name: str
    id: str = ""
    academic_year_id: Optional[str] = None
    start_date: Optional[str] = None  # ISO format: YYYY-MM-DD
    end_date: Optional[str] = None  # ISO format: YYYY-MM-DD


@dataclass
class MarkingPeriodData:
    """Framework-agnostic marking period data"""
    name: str
    start_date: str  # ISO format: YYYY-MM-DD
    end_date: str  # ISO format: YYYY-MM-DD
    semester_id: str
    id: str = ""
    short_name: Optional[str] = None
    description: Optional[str] = None


@dataclass
class GradeLevelData:
    """Framework-agnostic grade level data"""
    name: str
    id: str = ""
    level: int = 1
    short_name: Optional[str] = None
    description: Optional[str] = None
    order: int = 0


@dataclass
class SubjectData:
    """Framework-agnostic subject data"""
    name: str
    id: str = ""
    code: str = ""
    description: Optional[str] = None
    credits: Optional[float] = None
    category: Optional[str] = None


@dataclass
class SectionData:
    """Framework-agnostic section/class data"""
    name: str
    id: str = ""
    code: str = ""
    grade_level_id: Optional[str] = None
    max_capacity: Optional[int] = None
    room_number: Optional[str] = None
    description: Optional[str] = None


@dataclass
class DivisionData:
    """Framework-agnostic division data (e.g., Primary, Secondary)"""
    name: str
    id: str = ""
    description: Optional[str] = None
    order: int = 0


@dataclass
class PeriodData:
    """Framework-agnostic class period data"""
    name: str
    id: str = ""
    order: int = 0
    description: Optional[str] = None

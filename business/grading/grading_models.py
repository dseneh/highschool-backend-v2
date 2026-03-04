"""
Grading Data Models (DTOs)

Framework-agnostic data structures for grading module.
"""

from dataclasses import dataclass
from typing import Optional
from decimal import Decimal


@dataclass
class GradeLetterData:
    """Grade letter data transfer object"""
    id: str
    letter: str
    min_percentage: Decimal
    max_percentage: Decimal
    order: int


@dataclass
class AssessmentTypeData:
    """Assessment type data transfer object"""
    id: str
    name: str
    code: str
    description: Optional[str]
    weight: Decimal
    active: bool


@dataclass
class GradeBookData:
    """Gradebook data transfer object"""
    id: str
    section_subject_id: str
    academic_year_id: str
    name: str
    calculation_method: str
    active: bool


@dataclass
class AssessmentData:
    """Assessment/Grade item data transfer object"""
    id: str
    gradebook_id: str
    assessment_type_id: str
    marking_period_id: str
    name: str
    max_score: Decimal
    weight: Decimal
    due_date: Optional[str]
    active: bool


@dataclass
class GradeData:
    """Grade data transfer object"""
    id: str
    assessment_id: str
    student_id: str
    enrollment_id: str
    score: Optional[Decimal]
    status: str
    comments: Optional[str]

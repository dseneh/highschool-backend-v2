"""
Settings Data Models (DTOs)

Framework-agnostic data structures for settings module.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class GradingSettingsData:
    """Grading settings data transfer object"""
    id: str
    grading_style: str  # 'single_entry' or 'multiple_entry'
    single_entry_assessment_name: str
    use_default_templates: bool
    auto_calculate_final_grade: bool
    default_calculation_method: str  # 'average' or 'weighted'
    require_grade_approval: bool
    require_grade_review: bool
    display_assessment_on_single_entry: bool
    allow_assessment_delete: bool
    allow_assessment_create: bool
    allow_assessment_edit: bool
    use_letter_grades: bool
    allow_teacher_override: bool
    lock_grades_after_semester: bool
    display_grade_status: bool
    cumulative_average_calculation: bool
    notes: Optional[str] = None

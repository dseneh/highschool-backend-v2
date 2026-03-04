"""
Grading Adapters Module

Exports all grading Django database adapters.
"""

from .grade_adapter import (
    django_grade_to_data,
    django_assessment_to_data,
    django_grade_letter_to_data,
    get_assessment_by_id,
    get_grade_by_id,
    get_gradebook_by_id,
    get_enrollment_by_id,
    get_marking_period_by_id,
    get_assessment_type_by_id,
    create_grade_in_db,
    update_grade_in_db,
    delete_grade_from_db,
    get_grades_by_assessment,
    get_grades_by_student,
    get_grade_by_assessment_and_enrollment,
    bulk_create_grades_in_db,
    create_assessment_in_db,
    update_assessment_in_db,
    delete_assessment_from_db,
    get_assessments_by_gradebook,
    check_assessment_name_exists,
    create_grade_letter_in_db,
    update_grade_letter_in_db,
    delete_grade_letter_from_db,
    get_grade_letters_by_school,
    get_assessment_statistics,
    get_student_grade_summary,
)

__all__ = [
    # Data conversion
    'django_grade_to_data',
    'django_assessment_to_data',
    'django_grade_letter_to_data',
    
    # Lookup functions
    'get_assessment_by_id',
    'get_grade_by_id',
    'get_gradebook_by_id',
    'get_enrollment_by_id',
    'get_marking_period_by_id',
    'get_assessment_type_by_id',
    
    # Grade operations
    'create_grade_in_db',
    'update_grade_in_db',
    'delete_grade_from_db',
    'get_grades_by_assessment',
    'get_grades_by_student',
    'get_grade_by_assessment_and_enrollment',
    'bulk_create_grades_in_db',
    
    # Assessment operations
    'create_assessment_in_db',
    'update_assessment_in_db',
    'delete_assessment_from_db',
    'get_assessments_by_gradebook',
    'check_assessment_name_exists',
    
    # Grade letter operations
    'create_grade_letter_in_db',
    'update_grade_letter_in_db',
    'delete_grade_letter_from_db',
    'get_grade_letters_by_school',
    
    # Statistics
    'get_assessment_statistics',
    'get_student_grade_summary',
]

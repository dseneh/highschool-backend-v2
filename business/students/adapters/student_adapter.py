"""
Student Django Adapter - Database Operations

This module handles all Django-specific database operations for students.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional
from django.db.models import Q

from students.models import Student
from business.students.student_models import StudentData


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_student_to_data(student: Student) -> StudentData:
    """Convert Django Student model to plain data object"""
    return StudentData(
        id=str(student.id),
        id_number=student.id_number,
        first_name=student.first_name,
        last_name=student.last_name,
        middle_name=student.middle_name,
        date_of_birth=student.date_of_birth,
        gender=student.gender,
        status=student.status,
        grade_level_id=str(student.grade_level_id) if student.grade_level_id else None,
        email=student.email,
        phone=student.phone_number,
        address=student.address,
        entry_as=student.entry_as,
        prev_id_number=student.prev_id_number,
    )


# =============================================================================
# STUDENT DATABASE OPERATIONS
# =============================================================================

def create_student_in_db(data: dict, created_by=None, updated_by=None) -> Student:
    """
    Create student in database
    This is Django-specific and should only be called from Django views
    """
    student_data = {**data}
    
    # Add Django-specific fields
    if created_by:
        student_data['created_by'] = created_by
    if updated_by:
        student_data['updated_by'] = updated_by
    
    return Student.objects.create(**student_data)


def update_student_in_db(student: Student, data: dict, updated_by=None) -> Student:
    """
    Update student in database
    This is Django-specific and should only be called from Django views
    """
    for field, value in data.items():
        if hasattr(student, field):
            setattr(student, field, value)
    
    if updated_by:
        student.updated_by = updated_by
    
    student.save()
    return student


def delete_student_from_db(student: Student) -> bool:
    """
    Delete student from database
    Returns True if successful
    """
    try:
        student.delete()
        return True
    except Exception:
        return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_next_student_sequence() -> int:
    """Get next student sequence number for a school"""
    return Student.allocate_next_seq()


def check_student_exists(first_name: str, last_name: str, date_of_birth, 
                         prev_id_number: Optional[str] = None) -> bool:
    """Check if student already exists"""
    query = (
        Q(first_name=first_name) & 
        Q(last_name=last_name) & 
        Q(date_of_birth=date_of_birth)
    )
    
    if prev_id_number:
        query &= Q(prev_id_number=prev_id_number)
    
    return Student.objects.filter(query).exists()


def student_has_enrollments(student: Student) -> bool:
    """Check if student has any enrollment records"""
    return student.enrollments.exists()


def student_has_bills(student: Student) -> bool:
    """Check if student has any billing records"""
    return hasattr(student, 'bills') and student.bills.exists()

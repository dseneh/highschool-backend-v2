"""
Student Django Adapter - Database Operations

This module handles all Django-specific database operations for students.
Business logic should NOT be in this file - only database interactions.
"""

from datetime import datetime, date
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
    """Check if a student already exists using the same semantics across endpoints.

    A match is considered true when either condition matches:
    1) first_name + last_name + date_of_birth
    2) prev_id_number (when provided)
    """

    def _clean(value) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _parse_dob(value) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value

        text = str(value).strip()
        if not text:
            return None

        # Keep supported formats in sync with bulk import parsing behavior.
        formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%m/%d/%y",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y/%m/%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    first = _clean(first_name)
    last = _clean(last_name)
    prev_id = _clean(prev_id_number)
    dob = _parse_dob(date_of_birth)

    query = Q()

    # Condition 1: same person by name + DOB.
    if first and last and dob:
        query |= Q(first_name__iexact=first, last_name__iexact=last, date_of_birth=dob)

    # Condition 2: same person by previous id.
    if prev_id:
        query |= Q(prev_id_number__iexact=prev_id)

    if not query.children:
        return False

    return Student.objects.filter(query).exists()


def student_has_enrollments(student: Student) -> bool:
    """Check if student has any enrollment records"""
    return student.enrollments.exists()


def student_has_bills(student: Student) -> bool:
    """Check if student has any billing records"""
    return hasattr(student, 'bills') and student.bills.exists()

"""
Student business logic - Pure Python functions (no Django)
"""
from typing import List, Optional
from datetime import date, datetime
from business.students.student_models import StudentData, StudentValidationResult


def validate_student_data(student: StudentData) -> StudentValidationResult:
    """
    Validate student data according to business rules
    Returns validation result with errors and warnings
    """
    errors = []
    warnings = []
    
    # Required fields
    if not student.first_name:
        errors.append("First name is required")
    
    if not student.last_name:
        errors.append("Last name is required")
    
    if not student.date_of_birth:
        errors.append("Date of birth is required")
    
    if not student.gender:
        errors.append("Gender is required")
    elif student.gender.lower() not in ['male', 'female', 'm', 'f']:
        errors.append("Gender must be 'male' or 'female'")
    
    if not student.entry_as:
        errors.append("Entry type is required")
    elif student.entry_as not in ['new', 'returning', 'transferred']:
        errors.append("Entry type must be 'new', 'returning', or 'transferred'")
    
    # Age validation
    if student.date_of_birth:
        age = calculate_age(student.date_of_birth)
        if age < 3:
            warnings.append(f"Student is very young ({age} years old)")
        elif age > 25:
            warnings.append(f"Student is older than typical ({age} years old)")
    
    # Email validation (basic)
    if student.email:
        if '@' not in student.email or '.' not in student.email:
            errors.append("Invalid email format")
    
    return StudentValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )


def calculate_age(birth_date: date, reference_date: date = None) -> int:
    """
    Calculate age from birth date
    """
    if reference_date is None:
        reference_date = date.today()
    
    age = reference_date.year - birth_date.year
    
    # Adjust if birthday hasn't occurred this year
    if (reference_date.month, reference_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    
    return age


def get_student_full_name(student: StudentData, include_middle: bool = True) -> str:
    """
    Get student's full name
    """
    parts = []
    
    if student.first_name:
        parts.append(student.first_name)
    
    if include_middle and student.middle_name:
        parts.append(student.middle_name)
    
    if student.last_name:
        parts.append(student.last_name)
    
    return " ".join(parts) if parts else "Unknown"


def check_duplicate_student(
    students: List[StudentData],
    new_student: StudentData
) -> Optional[StudentData]:
    """
    Check if a student with same name and DOB already exists
    Returns the duplicate student if found, None otherwise
    """
    for student in students:
        if (student.first_name == new_student.first_name and
            student.last_name == new_student.last_name and
            student.date_of_birth == new_student.date_of_birth):
            return student
    
    return None


def validate_entry_type(entry_as: str, prev_id_number: Optional[str]) -> tuple[bool, Optional[str]]:
    """
    Validate entry type with business rules
    Returns: (is_valid, error_message)
    """
    if entry_as not in ['new', 'returning', 'transferred']:
        return False, "Invalid entry_as. Please select either 'new', 'returning', or 'transferred'."
    
    # If transferred, must have previous ID number
    if entry_as == 'transferred' and not prev_id_number:
        return False, "Previous ID number is required for transferred students"
    
    # If new, should not have previous ID
    if entry_as == 'new' and prev_id_number:
        return False, "New students should not have a previous ID number"
    
    return True, None


def validate_gender(gender: str) -> tuple[bool, Optional[str]]:
    """
    Validate gender value
    Returns: (is_valid, error_message)
    """
    if gender not in ["male", "female"]:
        return False, "Invalid gender. Please select either 'male' or 'female'."
    return True, None


def validate_student_creation(data: dict) -> tuple[bool, list[str]]:
    """
    Validate all required fields for student creation
    Returns: (is_valid, list_of_errors)
    """
    errors = []
    
    # Required fields
    required_fields = ["first_name", "last_name", "date_of_birth", "gender", "entry_as"]
    for field in required_fields:
        if not data.get(field):
            errors.append(f"{field.replace('_', ' ').title()} is required")
    
    # Validate gender
    if data.get("gender"):
        is_valid, error = validate_gender(data["gender"])
        if not is_valid:
            errors.append(error)
    
    # Validate entry type
    if data.get("entry_as"):
        is_valid, error = validate_entry_type(data["entry_as"], data.get("prev_id_number"))
        if not is_valid:
            errors.append(error)
    
    # Validate grade level
    if not data.get("grade_level"):
        errors.append("Current grade level is required.")
    
    return len(errors) == 0, errors


def filter_students_by_criteria(
    students: List[StudentData],
    gender: Optional[str] = None,
    status: Optional[str] = None,
    grade_level_id: Optional[str] = None,
    search: Optional[str] = None
) -> List[StudentData]:
    """
    Filter students by various criteria (for in-memory filtering)
    """
    filtered = students
    
    if gender:
        filtered = [s for s in filtered if s.gender and s.gender.lower() == gender.lower()]
    
    if status:
        filtered = [s for s in filtered if s.status == status]
    
    if grade_level_id:
        filtered = [s for s in filtered if s.grade_level_id == grade_level_id]
    
    if search:
        search_lower = search.lower()
        filtered = [
            s for s in filtered
            if (search_lower in (s.first_name or '').lower() or
                search_lower in (s.last_name or '').lower() or
                search_lower in (s.id_number or '').lower())
        ]
    
    return filtered


def generate_student_id(school_code: str, sequence_number: int) -> str:
    """
    Generate student ID from school code and sequence number
    Example: SCH-001-00001
    """
    return f"{school_code}-{sequence_number:05d}"


def prepare_student_data_for_creation(request_data: dict, school_code: int, student_seq: int) -> dict:
    """
    Prepare student data for creation.
    Extracts and structures data according to business rules.
    
    Args:
        request_data: Raw request data
        school_code: School code for ID generation
        student_seq: Next sequence number for student
        
    Returns:
        Structured data ready for persistence
    """
    return {
        "first_name": request_data.get("first_name"),
        "last_name": request_data.get("last_name"),
        "middle_name": request_data.get("middle_name"),
        "date_of_birth": request_data.get("date_of_birth"),
        "gender": request_data.get("gender"),
        "email": request_data.get("email"),
        "phone_number": request_data.get("phone_number"),
        "address": request_data.get("address"),
        "city": request_data.get("city"),
        "state": request_data.get("state"),
        "postal_code": request_data.get("postal_code"),
        "country": request_data.get("country"),
        "place_of_birth": request_data.get("place_of_birth"),
        "entry_as": request_data.get("entry_as", "new"),
        "entry_date": request_data.get("entry_date"),
        "prev_id_number": request_data.get("prev_id_number"),
        "school_code": school_code,
        "student_seq": student_seq,
    }


def should_auto_enroll(request_data: dict) -> bool:
    """
    Business rule: Determine if student should be auto-enrolled
    """
    return request_data.get("enroll_student", False) is True


def validate_student_update(student_data: StudentData, update_data: dict) -> tuple[bool, list[str]]:
    """
    Validate student update according to business rules
    
    Args:
        student_data: Current student data
        update_data: Data to update
        
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    # Can't change certain fields
    immutable_fields = ['id_number', 'school_code', 'student_seq']
    for field in immutable_fields:
        if field in update_data and update_data[field] != getattr(student_data, field, None):
            errors.append(f"Cannot change {field} after creation")
    
    # Validate gender if being updated
    if 'gender' in update_data and update_data['gender']:
        is_valid, error = validate_gender(update_data['gender'])
        if not is_valid:
            errors.append(error)
    
    return len(errors) == 0, errors


def can_delete_student(student_data: StudentData, has_enrollments: bool = False, has_bills: bool = False) -> tuple[bool, Optional[str]]:
    """
    Business rule: Can a student be deleted?
    
    Args:
        student_data: Student to check
        has_enrollments: Does student have enrollment records?
        has_bills: Does student have billing records?
        
    Returns:
        (can_delete, reason_if_not)
    """
    if has_enrollments:
        return False, "Cannot delete student with enrollment records"
    
    if has_bills:
        return False, "Cannot delete student with billing records"
    
    # Could add more rules like:
    # - Can't delete students with grades
    # - Can't delete students from past academic years
    # etc.
    
    return True, None


def parse_enrollment_status_filter(status_param: str) -> tuple[list[str], list[str]]:
    """
    Parse status parameter to extract enrollment statuses
    
    Args:
        status_param: Comma-separated status values
        
    Returns:
        (enrollment_statuses, other_statuses)
    """
    if not status_param:
        return [], []
    
    status_values = [s.strip().lower() for s in status_param.split(",") if s.strip()]
    
    enrollment_statuses = []
    other_statuses = []
    
    for s in status_values:
        if s == "all":
            continue
        if s in ["enrolled", "not enrolled", "not_enrolled"]:
            enrollment_statuses.append(s.replace(" ", "_"))
        else:
            other_statuses.append(s)
    
    return enrollment_statuses, other_statuses


def get_sorting_fields(ordering: str) -> tuple[list[str], bool]:
    """
    Business logic: Determine sorting fields from ordering parameter
    
    Args:
        ordering: Ordering parameter (e.g., 'id_number', '-full_name')
        
    Returns:
        (field_names, is_descending)
    """
    if not ordering:
        return ['id_number'], False
    
    is_descending = ordering.startswith('-')
    field = ordering.lstrip('-+')
    
    # Special handling for id_number (uses school_code and student_seq)
    if field == 'id_number':
        return ['school_code', 'student_seq'], is_descending
    
    # Special handling for full_name
    if field == 'full_name':
        return ['last_name', 'first_name'], is_descending
    
    return [field], is_descending

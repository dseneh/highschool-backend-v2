"""
Staff Business Service - Framework-Agnostic Business Logic

This module contains all business rules and validation logic for staff management.
NO Django or framework-specific imports allowed.
"""

from typing import Optional, Tuple, List
from datetime import date, datetime
from business.staff.staff_models import StaffData, StaffValidationResult, PositionData, DepartmentData


def validate_staff_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate staff creation data
    
    Args:
        data: Raw staff data dictionary
        
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    # Required fields
    required_fields = {
        'first_name': 'First name is required',
        'last_name': 'Last name is required',
        'gender': 'Gender is required',
        'hire_date': 'Hire date is required',
        'email': 'Email is required',
        'phone_number': 'Phone number is required',
        'date_of_birth': 'Date of birth is required',
    }
    
    for field, error_msg in required_fields.items():
        value = data.get(field)
        if not value or (isinstance(value, str) and not value.strip()):
            errors.append(error_msg)
    
    # Validate gender
    if data.get('gender'):
        gender_valid, gender_error = validate_gender(data['gender'])
        if not gender_valid:
            errors.append(gender_error)
    
    # Validate email format
    if data.get('email'):
        email_valid, email_error = validate_email_format(data['email'])
        if not email_valid:
            errors.append(email_error)
    
    # Validate employment status
    if data.get('status'):
        status_valid, status_error = validate_employment_status(data['status'])
        if not status_valid:
            errors.append(status_error)
    
    # Validate hire date
    if data.get('hire_date'):
        date_valid, date_error = validate_date_format(data['hire_date'])
        if not date_valid:
            errors.append(f"Invalid hire date: {date_error}")
    
    # Validate date of birth
    if data.get('date_of_birth'):
        dob_valid, dob_error = validate_date_format(data['date_of_birth'])
        if not dob_valid:
            errors.append(f"Invalid date of birth: {dob_error}")
        else:
            # Check if DOB is not in future
            age_valid, age_error = validate_age(data['date_of_birth'])
            if not age_valid:
                errors.append(age_error)
    
    return len(errors) == 0, errors


def validate_staff_update(data: dict, current_staff: StaffData) -> Tuple[bool, List[str]]:
    """
    Validate staff update data
    
    Args:
        data: Update data dictionary
        current_staff: Current staff data
        
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    # Validate gender if provided
    if 'gender' in data and data['gender']:
        gender_valid, gender_error = validate_gender(data['gender'])
        if not gender_valid:
            errors.append(gender_error)
    
    # Validate email if provided
    if 'email' in data and data['email']:
        email_valid, email_error = validate_email_format(data['email'])
        if not email_valid:
            errors.append(email_error)
    
    # Validate status if provided
    if 'status' in data and data['status']:
        status_valid, status_error = validate_employment_status(data['status'])
        if not status_valid:
            errors.append(status_error)
    
    # Validate dates if provided
    if 'hire_date' in data and data['hire_date']:
        date_valid, date_error = validate_date_format(data['hire_date'])
        if not date_valid:
            errors.append(f"Invalid hire date: {date_error}")
    
    if 'date_of_birth' in data and data['date_of_birth']:
        dob_valid, dob_error = validate_date_format(data['date_of_birth'])
        if not dob_valid:
            errors.append(f"Invalid date of birth: {dob_error}")
    
    return len(errors) == 0, errors


def can_delete_staff(staff_data: StaffData, has_user_account: bool = False, 
                     has_teaching_sections: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Business rule: Can a staff member be deleted?
    
    Args:
        staff_data: Staff to check
        has_user_account: Does staff have a linked user account?
        has_teaching_sections: Does staff have teaching sections assigned?
        
    Returns:
        (can_delete, reason_if_not)
    """
    if has_user_account:
        return False, "Cannot delete staff with an associated user account. Delete user account first."
    
    if has_teaching_sections:
        return False, "Cannot delete staff with assigned teaching sections"
    
    # Could add more rules:
    # - Staff with payroll records
    # - Staff with performance reviews
    # - etc.
    
    return True, None


def validate_gender(gender: str) -> Tuple[bool, Optional[str]]:
    """
    Validate gender value
    
    Returns:
        (is_valid, error_message)
    """
    valid_genders = ['male', 'female', 'other']
    if gender.lower() not in valid_genders:
        return False, f"Gender must be one of: {', '.join(valid_genders)}"
    return True, None


def validate_employment_status(status: str) -> Tuple[bool, Optional[str]]:
    """
    Validate employment status value
    
    Returns:
        (is_valid, error_message)
    """
    valid_statuses = ['active', 'inactive', 'suspended', 'terminated', 'on_leave', 'retired']
    if status.lower() not in valid_statuses:
        return False, f"Employment status must be one of: {', '.join(valid_statuses)}"
    return True, None


def validate_email_format(email: str) -> Tuple[bool, Optional[str]]:
    """
    Basic email format validation
    
    Returns:
        (is_valid, error_message)
    """
    email = email.strip()
    if '@' not in email or '.' not in email.split('@')[-1]:
        return False, "Invalid email format"
    if len(email) < 5:
        return False, "Email is too short"
    return True, None


def validate_date_format(date_string: str) -> Tuple[bool, Optional[str]]:
    """
    Validate date format (YYYY-MM-DD)
    
    Returns:
        (is_valid, error_message)
    """
    try:
        datetime.strptime(date_string, '%Y-%m-%d')
        return True, None
    except ValueError:
        return False, "Date must be in YYYY-MM-DD format"


def validate_age(date_of_birth: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that date of birth is not in the future and person is at least 16
    
    Returns:
        (is_valid, error_message)
    """
    try:
        dob = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
        today = date.today()
        
        if dob > today:
            return False, "Date of birth cannot be in the future"
        
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        
        if age < 16:
            return False, "Staff member must be at least 16 years old"
        
        if age > 100:
            return False, "Age seems invalid (over 100 years)"
        
        return True, None
    except ValueError:
        return False, "Invalid date of birth format"


def prepare_staff_data_for_creation(raw_data: dict) -> dict:
    """
    Prepare and normalize staff data for creation
    
    Args:
        raw_data: Raw request data
        
    Returns:
        Cleaned and normalized data dictionary
    """
    return {
        'first_name': raw_data.get('first_name', '').strip(),
        'middle_name': raw_data.get('middle_name', '').strip() or None,
        'last_name': raw_data.get('last_name', '').strip(),
        'gender': raw_data.get('gender', '').lower().strip(),
        'email': raw_data.get('email', '').strip().lower(),
        'phone_number': raw_data.get('phone_number', '').strip(),
        'date_of_birth': raw_data.get('date_of_birth'),
        'hire_date': raw_data.get('hire_date'),
        'status': raw_data.get('status', 'active').lower().strip(),
        'address': raw_data.get('address', '').strip() or None,
        'city': raw_data.get('city', '').strip() or None,
        'state': raw_data.get('state', '').strip() or None,
        'postal_code': raw_data.get('postal_code', '').strip() or None,
        'country': raw_data.get('country', '').strip() or None,
        'place_of_birth': raw_data.get('place_of_birth', '').strip() or None,
        'id_number': raw_data.get('id_number', '').strip() or None,
        'position_id': raw_data.get('position'),
        'primary_department_id': raw_data.get('primary_department'),
        'is_teacher': raw_data.get('is_teacher', False),
    }


def should_auto_generate_id(id_number: Optional[str]) -> bool:
    """
    Business rule: Should we auto-generate staff ID?
    
    Returns:
        True if ID should be auto-generated
    """
    return not id_number or not id_number.strip()


def get_staff_full_name(first_name: str, last_name: str, middle_name: Optional[str] = None) -> str:
    """
    Format staff full name
    
    Returns:
        Formatted full name
    """
    if middle_name:
        return f"{first_name} {middle_name} {last_name}"
    return f"{first_name} {last_name}"


def calculate_years_of_service(hire_date_str: str) -> Optional[int]:
    """
    Calculate years of service from hire date
    
    Args:
        hire_date_str: Hire date in YYYY-MM-DD format
        
    Returns:
        Years of service or None if invalid date
    """
    try:
        hire_date = datetime.strptime(hire_date_str, '%Y-%m-%d').date()
        today = date.today()
        years = today.year - hire_date.year
        if (today.month, today.day) < (hire_date.month, hire_date.day):
            years -= 1
        return max(0, years)
    except (ValueError, AttributeError):
        return None


def is_eligible_for_promotion(staff_data: StaffData, min_years: int = 2) -> Tuple[bool, Optional[str]]:
    """
    Business rule: Is staff eligible for promotion?
    
    Args:
        staff_data: Staff information
        min_years: Minimum years of service required
        
    Returns:
        (is_eligible, reason_if_not)
    """
    if staff_data.status.lower() != 'active':
        return False, "Only active staff can be promoted"
    
    if not staff_data.hire_date:
        return False, "Hire date not set"
    
    years_of_service = calculate_years_of_service(staff_data.hire_date)
    if years_of_service is None:
        return False, "Invalid hire date"
    
    if years_of_service < min_years:
        return False, f"Requires at least {min_years} years of service (has {years_of_service})"
    
    return True, None


def should_create_user_account(initialize_user: any) -> bool:
    """
    Business rule: Should we create a user account for this staff?
    
    Args:
        initialize_user: Value from request (can be bool, string, etc.)
        
    Returns:
        True if user account should be created
    """
    if isinstance(initialize_user, bool):
        return initialize_user
    if isinstance(initialize_user, str):
        return initialize_user.lower() in ('true', '1', 'yes')
    return False


def get_allowed_creation_fields() -> List[str]:
    """
    Business rule: What fields are allowed during staff creation?
    
    Returns:
        List of allowed field names
    """
    return [
        'first_name',
        'middle_name',
        'last_name',
        'date_of_birth',
        'gender',
        'email',
        'phone_number',
        'address',
        'city',
        'state',
        'postal_code',
        'country',
        'place_of_birth',
        'status',
        'hire_date',
        'id_number',
        'position',
        'primary_department',
        'is_teacher',
    ]


def get_allowed_update_fields() -> List[str]:
    """
    Business rule: What fields are allowed during staff update?
    
    Returns:
        List of allowed field names
    """
    return [
        'first_name',
        'middle_name',
        'last_name',
        'date_of_birth',
        'gender',
        'email',
        'phone_number',
        'address',
        'city',
        'state',
        'postal_code',
        'country',
        'place_of_birth',
        'status',
        'hire_date',
        'primary_department',
        'id_number',
        'position',
        'photo',
        'is_teacher',
        'suspension_date',
        'suspension_reason',
        'termination_date',
        'termination_reason',
        'manager',
    ]


# Position Business Logic

def validate_position_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate position creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not data.get('title') or not data.get('title').strip():
        errors.append("Position title is required")
    
    if data.get('employment_type'):
        employment_types = ['full_time', 'part_time', 'contract', 'temporary', 'intern']
        if data['employment_type'].lower() not in employment_types:
            errors.append(f"Invalid employment type. Must be one of: {', '.join(employment_types)}")
    
    if data.get('compensation_type'):
        compensation_types = ['salary', 'hourly', 'stipend']
        if data['compensation_type'].lower() not in compensation_types:
            errors.append(f"Invalid compensation type. Must be one of: {', '.join(compensation_types)}")
    
    # Validate salary range
    salary_min = data.get('salary_min')
    salary_max = data.get('salary_max')
    if salary_min is not None and salary_max is not None:
        try:
            if float(salary_min) > float(salary_max):
                errors.append("Minimum salary cannot be greater than maximum salary")
        except (ValueError, TypeError):
            errors.append("Invalid salary range values")
    
    return len(errors) == 0, errors


# Department Business Logic

def validate_department_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate department creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not data.get('name') or not data.get('name').strip():
        errors.append("Department name is required")
    
    return len(errors) == 0, errors

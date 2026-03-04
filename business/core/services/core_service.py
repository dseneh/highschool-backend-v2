"""
Core Business Service - Framework-Agnostic Business Logic

This module contains all business rules and validation logic for core system entities.
NO Django or framework-specific imports allowed.
"""

from typing import Optional, Tuple, List
from datetime import date, datetime, timedelta


# =============================================================================
# ACADEMIC YEAR BUSINESS LOGIC
# =============================================================================

def validate_academic_year_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate academic year creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    # Required fields
    if not data.get('start_date'):
        errors.append("Start date is required")
    if not data.get('end_date'):
        errors.append("End date is required")
    
    # Validate dates
    if data.get('start_date') and data.get('end_date'):
        date_valid, date_error = validate_date_range(
            data['start_date'], 
            data['end_date']
        )
        if not date_valid:
            errors.append(date_error)
        
        # Check duration
        duration_valid, duration_error = validate_academic_year_duration(
            data['start_date'],
            data['end_date']
        )
        if not duration_valid:
            errors.append(duration_error)
    
    return len(errors) == 0, errors


def validate_academic_year_duration(start_date: str, end_date: str) -> Tuple[bool, Optional[str]]:
    """
    Business rule: Academic year cannot be more than 1 year (365 days)
    
    Returns:
        (is_valid, error_message)
    """
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        duration = (end - start).days
        
        if duration > 365:
            return False, "Academic year cannot be more than 1 year (365 days)"
        
        if duration < 30:
            return False, "Academic year must be at least 30 days"
        
        return True, None
    except ValueError as e:
        return False, f"Invalid date format: {str(e)}"


def check_academic_year_overlap(start_date: str, end_date: str, 
                                 existing_years: List[dict]) -> bool:
    """
    Check if new academic year overlaps with existing ones
    
    Args:
        start_date: New year start date (YYYY-MM-DD)
        end_date: New year end date (YYYY-MM-DD)
        existing_years: List of existing academic years with start_date and end_date
        
    Returns:
        True if overlaps, False otherwise
    """
    try:
        new_start = datetime.strptime(start_date, '%Y-%m-%d').date()
        new_end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        for year in existing_years:
            existing_start = datetime.strptime(year['start_date'], '%Y-%m-%d').date()
            existing_end = datetime.strptime(year['end_date'], '%Y-%m-%d').date()
            
            # Check for overlap: new_start < existing_end AND new_end > existing_start
            if new_start < existing_end and new_end > existing_start:
                return True
        
        return False
    except (ValueError, KeyError):
        return False


def generate_academic_year_name(start_date: str, end_date: str) -> str:
    """
    Generate academic year name from dates (e.g., "2024/2025")
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        
    Returns:
        Academic year name
    """
    try:
        start_year = datetime.strptime(start_date, '%Y-%m-%d').year
        end_year = datetime.strptime(end_date, '%Y-%m-%d').year
        return f"{start_year}/{end_year}"
    except ValueError:
        return "Academic Year"


# =============================================================================
# GRADE LEVEL BUSINESS LOGIC
# =============================================================================

def validate_grade_level_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate grade level creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not data.get('name') or not data.get('name').strip():
        errors.append("Grade level name is required")
    
    level = data.get('level')
    if level is not None:
        try:
            level_int = int(level)
            if level_int < 1 or level_int > 20:
                errors.append("Grade level must be between 1 and 20")
        except (ValueError, TypeError):
            errors.append("Grade level must be a valid number")
    
    return len(errors) == 0, errors


# =============================================================================
# SUBJECT BUSINESS LOGIC
# =============================================================================

def validate_subject_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate subject creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not data.get('name') or not data.get('name').strip():
        errors.append("Subject name is required")
    
    credits = data.get('credits')
    if credits is not None:
        try:
            credits_float = float(credits)
            if credits_float < 0:
                errors.append("Credits cannot be negative")
            if credits_float > 10:
                errors.append("Credits cannot exceed 10")
        except (ValueError, TypeError):
            errors.append("Credits must be a valid number")
    
    return len(errors) == 0, errors


# =============================================================================
# SECTION BUSINESS LOGIC
# =============================================================================

def validate_section_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate section creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not data.get('name') or not data.get('name').strip():
        errors.append("Section name is required")
    
    capacity = data.get('capacity')
    if capacity is not None:
        try:
            capacity_int = int(capacity)
            if capacity_int < 1:
                errors.append("Capacity must be at least 1")
            if capacity_int > 1000:
                errors.append("Capacity cannot exceed 1000 students")
        except (ValueError, TypeError):
            errors.append("Capacity must be a valid number")
    
    return len(errors) == 0, errors


# =============================================================================
# SEMESTER/MARKING PERIOD BUSINESS LOGIC
# =============================================================================

def validate_semester_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate semester creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not data.get('name') or not data.get('name').strip():
        errors.append("Semester name is required")
    
    # If dates provided, validate them
    if data.get('start_date') and data.get('end_date'):
        date_valid, date_error = validate_date_range(
            data['start_date'],
            data['end_date']
        )
        if not date_valid:
            errors.append(date_error)
    
    return len(errors) == 0, errors


def validate_marking_period_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate marking period creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not data.get('name') or not data.get('name').strip():
        errors.append("Marking period name is required")
    
    if not data.get('start_date'):
        errors.append("Start date is required")
    
    if not data.get('end_date'):
        errors.append("End date is required")
    
    if data.get('start_date') and data.get('end_date'):
        date_valid, date_error = validate_date_range(
            data['start_date'],
            data['end_date']
        )
        if not date_valid:
            errors.append(date_error)
    
    return len(errors) == 0, errors


# =============================================================================
# SCHOOL BUSINESS LOGIC
# =============================================================================

def validate_school_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    required_fields = {
        'name': 'Name is required',
        'country': 'Country is required',
        'workspace': 'Workspace identifier is required',
    }
    
    for field, error_msg in required_fields.items():
        if not data.get(field) or not str(data.get(field)).strip():
            errors.append(error_msg)
    
    # Validate workspace format (alphanumeric, lowercase, hyphens)
    workspace = data.get('workspace', '')
    if workspace:
        workspace_valid, workspace_error = validate_workspace_format(workspace)
        if not workspace_valid:
            errors.append(workspace_error)
    
    # Validate email if provided
    email = data.get('email')
    if email and email.strip():
        email_valid, email_error = validate_email_format(email)
        if not email_valid:
            errors.append(email_error)
    
    # Validate website if provided
    website = data.get('website')
    if website and website.strip():
        url_valid, url_error = validate_url_format(website)
        if not url_valid:
            errors.append(f"Website: {url_error}")
    
    return len(errors) == 0, errors


def validate_workspace_format(workspace: str) -> Tuple[bool, Optional[str]]:
    """
    Validate workspace identifier format
    
    Business rules:
    - Only lowercase letters, numbers, and hyphens
    - Must start with a letter
    - 3-50 characters long
    
    Returns:
        (is_valid, error_message)
    """
    import re
    
    if len(workspace) < 3:
        return False, "Workspace must be at least 3 characters long"
    
    if len(workspace) > 50:
        return False, "Workspace cannot exceed 50 characters"
    
    # Must start with letter, contain only lowercase letters, numbers, hyphens
    pattern = r'^[a-z][a-z0-9-]*$'
    if not re.match(pattern, workspace):
        return False, "Workspace must start with a letter and contain only lowercase letters, numbers, and hyphens"
    
    # No consecutive hyphens
    if '--' in workspace:
        return False, "Workspace cannot contain consecutive hyphens"
    
    # Cannot end with hyphen
    if workspace.endswith('-'):
        return False, "Workspace cannot end with a hyphen"
    
    return True, None


# =============================================================================
# COMMON VALIDATION HELPERS
# =============================================================================

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


def validate_date_range(start_date: str, end_date: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that end date is after start date
    
    Returns:
        (is_valid, error_message)
    """
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        if start > end:
            return False, "Start date cannot be after end date"
        
        if start == end:
            return False, "Start date and end date cannot be the same"
        
        return True, None
    except ValueError:
        return False, "Invalid date format. Use YYYY-MM-DD"


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


def validate_url_format(url: str) -> Tuple[bool, Optional[str]]:
    """
    Basic URL format validation
    
    Returns:
        (is_valid, error_message)
    """
    url = url.strip().lower()
    if not url.startswith(('http://', 'https://')):
        return False, "URL must start with http:// or https://"
    if len(url) < 10:
        return False, "URL is too short"
    return True, None


# =============================================================================
# BUSINESS RULES
# =============================================================================

def can_set_academic_year_as_current(current_year_exists: bool) -> Tuple[bool, Optional[str]]:
    """
    Business rule: Can we set this academic year as current?
    
    Args:
        current_year_exists: Does a current academic year already exist?
        
    Returns:
        (can_set, reason_if_not)
    """
    # Only one academic year can be current at a time
    # This will be handled by unsetting the existing current year
    return True, None


def should_auto_generate_year_name(name: Optional[str]) -> bool:
    """
    Business rule: Should we auto-generate the academic year name?
    
    Returns:
        True if name should be auto-generated
    """
    return not name or not name.strip()

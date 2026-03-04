"""
Additional Core Service - Business Logic for Supporting Entities

Framework-agnostic business logic for Period, PeriodTime, SectionSchedule, SectionSubject, and GradeLevelTuitionFee.
NO Django or framework-specific imports allowed.
"""

from typing import List, Tuple, Dict, Any, Optional


# =============================================================================
# GRADE LEVEL TUITION FEE VALIDATION
# =============================================================================

def validate_tuition_fee_update(fee_id: Optional[str], amount: Optional[float]) -> Tuple[bool, Optional[str]]:
    """
    Validate individual tuition fee update data
    
    Args:
        fee_id: Fee identifier
        amount: Fee amount
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not fee_id:
        return False, "Fee ID is required"
    
    if amount is None:
        return False, f"Amount is required for fee ID {fee_id}"
    
    if amount < 0:
        return False, f"Amount must be non-negative for fee ID {fee_id}"
    
    return True, None


def validate_tuition_fees_bulk_update(tuition_fees: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Validate bulk tuition fee update data
    
    Args:
        tuition_fees: List of tuition fee data
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    if not tuition_fees:
        return False, ["tuition_fees array is required"]
    
    errors = []
    
    for fee_data in tuition_fees:
        is_valid, error = validate_tuition_fee_update(
            fee_data.get("id"),
            fee_data.get("amount")
        )
        if not is_valid:
            errors.append(error)
    
    return len(errors) == 0, errors


# =============================================================================
# PERIOD VALIDATION
# =============================================================================

def validate_period_creation(name: str) -> Tuple[bool, Optional[str]]:
    """
    Validate period creation data
    
    Args:
        name: Period name
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, "Name is required"
    
    if not name.strip():
        return False, "Name cannot be empty or whitespace"
    
    return True, None


def validate_period_name_uniqueness(name: str, existing_names: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Check if period name already exists (case-insensitive)
    
    Args:
        name: Period name to check
        existing_names: List of existing period names
        
    Returns:
        Tuple of (is_unique, error_message)
    """
    if name.lower() in [n.lower() for n in existing_names]:
        return False, "Period already exists"
    
    return True, None


# =============================================================================
# PERIOD TIME VALIDATION
# =============================================================================

def validate_period_time_creation(name: str, period_id: str) -> Tuple[bool, Optional[str]]:
    """
    Validate period time creation data
    
    Args:
        name: Period time name
        period_id: Parent period identifier
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, "Name is required"
    
    if not name.strip():
        return False, "Name cannot be empty or whitespace"
    
    if not period_id:
        return False, "Period ID is required"
    
    return True, None


# =============================================================================
# SECTION SCHEDULE VALIDATION
# =============================================================================

def validate_section_schedule_creation(subject_id: Optional[str], period_id: Optional[str],
                                       period_time_id: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate section schedule creation data
    
    Args:
        subject_id: Subject identifier
        period_id: Period identifier
        period_time_id: Period time identifier
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not subject_id:
        return False, "Subject is required"
    
    if not period_id:
        return False, "Period is required"
    
    if not period_time_id:
        return False, "Period time is required"
    
    return True, None


def validate_period_time_belongs_to_period(period_time_period_id: str, expected_period_id: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that period time belongs to the specified period
    
    Args:
        period_time_period_id: Period ID from period time
        expected_period_id: Expected period ID
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if period_time_period_id != expected_period_id:
        return False, "Period time does not belong to this period"
    
    return True, None


def check_section_schedule_exists(existing_schedules: List[Dict[str, str]], 
                                  subject_id: str, period_id: str, 
                                  period_time_id: str) -> bool:
    """
    Check if a section schedule already exists
    
    Args:
        existing_schedules: List of existing schedule data
        subject_id: Subject identifier
        period_id: Period identifier
        period_time_id: Period time identifier
        
    Returns:
        bool: True if schedule exists
    """
    for schedule in existing_schedules:
        if (schedule.get('subject_id') == subject_id and 
            schedule.get('period_id') == period_id and 
            schedule.get('period_time_id') == period_time_id):
            return True
    return False


# =============================================================================
# SECTION SUBJECT VALIDATION
# =============================================================================

def validate_section_subject_assignment(subject_ids: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate section subject assignment data
    
    Args:
        subject_ids: List of subject identifiers
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not subject_ids:
        return False, "Subject(s) are required"
    
    if not isinstance(subject_ids, list):
        return False, "subjects must be a list"
    
    if len(subject_ids) == 0:
        return False, "At least one subject is required"
    
    return True, None


def process_section_subject_assignments(subject_ids: List[str], 
                                        existing_subject_ids: List[str]) -> Dict[str, List[str]]:
    """
    Process section subject assignments and categorize them
    
    Args:
        subject_ids: List of subject IDs to assign
        existing_subject_ids: List of already assigned subject IDs
        
    Returns:
        dict: Categorized results with 'new', 'existing', 'invalid' lists
    """
    new_subjects = []
    existing_subjects = []
    
    for subject_id in subject_ids:
        if subject_id in existing_subject_ids:
            existing_subjects.append(subject_id)
        else:
            new_subjects.append(subject_id)
    
    return {
        'new': new_subjects,
        'existing': existing_subjects,
    }


def can_delete_section_subject(has_enrollments: bool) -> Tuple[bool, Optional[str]]:
    """
    Check if a section subject can be deleted
    
    Args:
        has_enrollments: Whether section has enrollments
        
    Returns:
        Tuple of (can_delete, reason_message)
    """
    if has_enrollments:
        return False, "Cannot delete subject, it is associated with a section. Subject has been deactivated."
    
    return True, None


# =============================================================================
# BULK OPERATION HELPERS
# =============================================================================

def prepare_bulk_update_response(updated_count: int, errors: List[str]) -> Dict[str, Any]:
    """
    Prepare response for bulk update operations
    
    Args:
        updated_count: Number of successfully updated items
        errors: List of error messages
        
    Returns:
        dict: Response data
    """
    if errors:
        return {
            'success': False,
            'updated_count': 0,
            'errors': errors,
            'message': 'No items were updated due to errors'
        }
    
    return {
        'success': True,
        'updated_count': updated_count,
        'message': f'{updated_count} item(s) updated successfully'
    }


def prepare_bulk_create_response(created_count: int, skipped_count: int, 
                                 errors: List[str]) -> Dict[str, Any]:
    """
    Prepare response for bulk create operations
    
    Args:
        created_count: Number of successfully created items
        skipped_count: Number of skipped items (already exist)
        errors: List of error messages
        
    Returns:
        dict: Response data
    """
    if errors and created_count == 0:
        return {
            'success': False,
            'created_count': 0,
            'skipped_count': 0,
            'errors': errors,
            'message': 'No items were created due to errors'
        }
    
    if created_count > 0 and skipped_count > 0:
        return {
            'success': True,
            'created_count': created_count,
            'skipped_count': skipped_count,
            'message': f'{created_count} item(s) created, {skipped_count} skipped (already exist)'
        }
    
    if created_count > 0:
        return {
            'success': True,
            'created_count': created_count,
            'message': f'All {created_count} item(s) assigned successfully'
        }
    
    return {
        'success': False,
        'created_count': 0,
        'message': 'No new items were assigned (all items already exist)'
    }

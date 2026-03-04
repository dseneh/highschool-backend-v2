"""
Grade Service - Pure Business Logic

This module contains all business logic for grade calculations and validation.
NO Django dependencies - only pure Python validation and business rules.
"""

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP


# =============================================================================
# GRADE CALCULATION FUNCTIONS
# =============================================================================

def calculate_percentage(score: Decimal, max_score: Decimal) -> Decimal:
    """
    Calculate percentage score
    
    Args:
        score: Student's score
        max_score: Maximum possible score
        
    Returns:
        Percentage score (0-100)
    """
    if max_score <= 0:
        return Decimal('0')
    
    percentage = (score / max_score) * Decimal('100')
    return percentage.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def get_letter_grade(percentage: Decimal, grade_letters: List[Dict]) -> Optional[str]:
    """
    Get letter grade based on percentage
    
    Args:
        percentage: Percentage score
        grade_letters: List of grade letter ranges (sorted by max_percentage desc)
        
    Returns:
        Letter grade or None if not found
    """
    for letter_data in grade_letters:
        min_pct = Decimal(str(letter_data['min_percentage']))
        max_pct = Decimal(str(letter_data['max_percentage']))
        
        if min_pct <= percentage <= max_pct:
            return letter_data['letter']
    
    return None


def calculate_weighted_average(grades: List[Dict]) -> Optional[Decimal]:
    """
    Calculate weighted average of grades
    
    Args:
        grades: List of grade dictionaries with 'score', 'max_score', and 'weight'
        
    Returns:
        Weighted average percentage or None if no valid grades
    """
    if not grades:
        return None
    
    total_weighted_score = Decimal('0')
    total_weight = Decimal('0')
    
    for grade in grades:
        score = Decimal(str(grade.get('score', 0)))
        max_score = Decimal(str(grade.get('max_score', 100)))
        weight = Decimal(str(grade.get('weight', 1)))
        
        if max_score > 0:
            percentage = calculate_percentage(score, max_score)
            total_weighted_score += percentage * weight
            total_weight += weight
    
    if total_weight == 0:
        return None
    
    weighted_avg = total_weighted_score / total_weight
    return weighted_avg.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_simple_average(grades: List[Dict]) -> Optional[Decimal]:
    """
    Calculate simple average of grades (unweighted)
    
    Args:
        grades: List of grade dictionaries with 'score' and 'max_score'
        
    Returns:
        Simple average percentage or None if no valid grades
    """
    if not grades:
        return None
    
    total_percentage = Decimal('0')
    count = 0
    
    for grade in grades:
        score = Decimal(str(grade.get('score', 0)))
        max_score = Decimal(str(grade.get('max_score', 100)))
        
        if max_score > 0:
            percentage = calculate_percentage(score, max_score)
            total_percentage += percentage
            count += 1
    
    if count == 0:
        return None
    
    avg = total_percentage / Decimal(str(count))
    return avg.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_score(score: Decimal, max_score: Decimal) -> Optional[str]:
    """
    Validate grade score
    
    Args:
        score: Student's score
        max_score: Maximum possible score
        
    Returns:
        Error message or None if valid
    """
    if score < 0:
        return "Score cannot be negative"
    
    if score > max_score:
        return f"Score cannot exceed maximum score of {max_score}"
    
    return None


def validate_grade_status(status: str) -> Optional[str]:
    """
    Validate grade status
    
    Args:
        status: Grade status
        
    Returns:
        Error message or None if valid
    """
    valid_statuses = ['draft', 'submitted', 'graded', 'published']
    
    if status not in valid_statuses:
        return f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
    
    return None


def can_edit_grade_status(current_status: str, new_status: str) -> Tuple[bool, Optional[str]]:
    """
    Check if grade status transition is valid
    
    Args:
        current_status: Current grade status
        new_status: New status to transition to
        
    Returns:
        Tuple of (can_edit, error_message)
    """
    # Define allowed transitions
    allowed_transitions = {
        'draft': ['submitted', 'graded', 'published'],
        'submitted': ['graded', 'published'],
        'graded': ['published'],
        'published': []  # Cannot change published grades
    }
    
    if current_status == 'published':
        return False, "Cannot modify published grades"
    
    if new_status not in allowed_transitions.get(current_status, []):
        return False, f"Cannot transition from {current_status} to {new_status}"
    
    return True, None


def validate_assessment_creation_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate assessment creation data
    
    Args:
        data: Assessment data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    required_fields = ['name', 'gradebook_id', 'assessment_type_id', 'marking_period_id']
    
    # Check required fields
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Validate max_score
    try:
        max_score = Decimal(str(data.get('max_score', 100)))
        if max_score <= 0:
            return None, "Maximum score must be greater than 0"
    except (ValueError, TypeError):
        return None, "Invalid max_score format"
    
    # Validate weight
    try:
        weight = Decimal(str(data.get('weight', 1)))
        if weight < 0:
            return None, "Weight cannot be negative"
    except (ValueError, TypeError):
        return None, "Invalid weight format"
    
    # Build validated data
    validated_data = {
        'name': data['name'].strip(),
        'gradebook_id': data['gradebook_id'],
        'assessment_type_id': data['assessment_type_id'],
        'marking_period_id': data['marking_period_id'],
        'max_score': max_score,
        'weight': weight,
        'due_date': data.get('due_date'),
        'active': data.get('active', True),
    }
    
    return validated_data, None


def validate_due_date(due_date: str, marking_period_start: str, 
                     marking_period_end: str) -> Optional[str]:
    """
    Validate due date is within marking period
    
    Args:
        due_date: Due date string (YYYY-MM-DD)
        marking_period_start: Marking period start date
        marking_period_end: Marking period end date
        
    Returns:
        Error message or None if valid
    """
    if not due_date:
        return None  # Optional field
    
    try:
        due_date_obj = datetime.strptime(due_date, "%Y-%m-%d").date()
        start_date = datetime.strptime(marking_period_start, "%Y-%m-%d").date()
        end_date = datetime.strptime(marking_period_end, "%Y-%m-%d").date()
    except ValueError:
        return "Invalid date format. Use YYYY-MM-DD format."
    
    if not (start_date <= due_date_obj <= end_date):
        return f"Due date must be within the marking period ({marking_period_start} - {marking_period_end})"
    
    return None


def validate_grade_creation_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate grade creation data
    
    Args:
        data: Grade data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    required_fields = ['assessment_id', 'enrollment_id']
    
    # Check required fields
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Validate score if provided
    score = None
    if data.get('score') is not None:
        try:
            score = Decimal(str(data['score']))
        except (ValueError, TypeError):
            return None, "Invalid score format"
    
    # Validate status
    status = data.get('status', 'draft')
    status_error = validate_grade_status(status)
    if status_error:
        return None, status_error
    
    # Build validated data
    validated_data = {
        'assessment_id': data['assessment_id'],
        'enrollment_id': data['enrollment_id'],
        'score': score,
        'status': status,
        'comments': data.get('comments', '').strip(),
    }
    
    return validated_data, None


def validate_grade_letter_creation_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate grade letter creation data
    
    Args:
        data: Grade letter data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    required_fields = ['letter', 'min_percentage', 'max_percentage']
    
    # Check required fields
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Validate percentages
    try:
        min_pct = Decimal(str(data['min_percentage']))
        max_pct = Decimal(str(data['max_percentage']))
    except (ValueError, TypeError):
        return None, "Invalid percentage format"
    
    if min_pct < 0 or max_pct > 100:
        return None, "Percentages must be between 0 and 100"
    
    if min_pct > max_pct:
        return None, "Minimum percentage cannot be greater than maximum percentage"
    
    # Build validated data
    validated_data = {
        'letter': data['letter'].strip().upper(),
        'min_percentage': min_pct,
        'max_percentage': max_pct,
        'order': data.get('order', 0),
    }
    
    return validated_data, None


# =============================================================================
# BUSINESS LOGIC FUNCTIONS
# =============================================================================

def check_grade_overlap(new_min: Decimal, new_max: Decimal, 
                       existing_letters: List[Dict], exclude_id: Optional[str] = None) -> Optional[str]:
    """
    Check if grade letter range overlaps with existing ranges
    
    Args:
        new_min: New minimum percentage
        new_max: New maximum percentage
        existing_letters: List of existing grade letters
        exclude_id: ID to exclude from overlap check (for updates)
        
    Returns:
        Error message or None if no overlap
    """
    for letter in existing_letters:
        if exclude_id and letter.get('id') == exclude_id:
            continue
        
        min_pct = Decimal(str(letter['min_percentage']))
        max_pct = Decimal(str(letter['max_percentage']))
        
        # Check if ranges overlap
        if new_min <= max_pct and new_max >= min_pct:
            return f"Percentage range {new_min}-{new_max}% overlaps with existing letter '{letter['letter']}' ({min_pct}-{max_pct}%)"
    
    return None


def get_grade_statistics(grades: List[Dict]) -> Dict:
    """
    Calculate statistics for a set of grades
    
    Args:
        grades: List of grade dictionaries with 'score' and 'max_score'
        
    Returns:
        Dictionary with statistics (average, min, max, count)
    """
    if not grades:
        return {
            'count': 0,
            'average': None,
            'min': None,
            'max': None,
        }
    
    scores = []
    for grade in grades:
        if grade.get('score') is not None:
            score = Decimal(str(grade['score']))
            max_score = Decimal(str(grade.get('max_score', 100)))
            if max_score > 0:
                percentage = calculate_percentage(score, max_score)
                scores.append(percentage)
    
    if not scores:
        return {
            'count': 0,
            'average': None,
            'min': None,
            'max': None,
        }
    
    return {
        'count': len(scores),
        'average': sum(scores) / len(scores),
        'min': min(scores),
        'max': max(scores),
    }

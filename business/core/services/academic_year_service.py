"""
Academic Year Business Logic

Pure Python business logic for academic years - no Django dependencies.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List


def validate_date_format(date_str: str) -> Optional[str]:
    """Validate date string format (YYYY-MM-DD)"""
    if not date_str:
        return None
    
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        return None


def validate_academic_year_creation(
    start_date: Optional[str],
    end_date: Optional[str],
    name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate academic year creation data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not start_date:
        return {"valid": False, "error": "Start date is required"}
    
    if not end_date:
        return {"valid": False, "error": "End date is required"}
    
    # Validate date formats
    validated_start = validate_date_format(start_date)
    if not validated_start:
        return {"valid": False, "error": "Invalid start date format. Use YYYY-MM-DD"}
    
    validated_end = validate_date_format(end_date)
    if not validated_end:
        return {"valid": False, "error": "Invalid end date format. Use YYYY-MM-DD"}
    
    # Convert to date objects for comparison
    start_date_obj = datetime.strptime(validated_start, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(validated_end, "%Y-%m-%d").date()
    
    # Validate date range
    if start_date_obj >= end_date_obj:
        return {"valid": False, "error": "Start date must be before end date"}
    
    # Validate duration
    duration_result = validate_academic_year_duration(start_date_obj, end_date_obj)
    if not duration_result["valid"]:
        return duration_result
    
    return {
        "valid": True,
        "data": {
            "start_date": start_date_obj,
            "end_date": end_date_obj,
            "name": name,
        },
        "error": None
    }


def validate_academic_year_duration(start_date, end_date) -> Dict[str, Any]:
    """
    Validate academic year duration is between 30 days and 365 days
    
    Args:
        start_date: Date object for start
        end_date: Date object for end
        
    Returns:
        dict with 'valid' (bool) and 'error' (str) keys
    """
    duration_days = (end_date - start_date).days
    
    if duration_days < 30:
        return {
            "valid": False,
            "error": "Academic year must be at least 30 days"
        }
    
    if duration_days > 365:
        return {
            "valid": False,
            "error": "Academic year cannot be more than 365 days"
        }
    
    return {"valid": True, "error": None}


def check_academic_year_overlap(
    start_date,
    end_date,
    existing_years: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    Check if academic year dates overlap with existing years
    
    Args:
        start_date: Date object for new year
        end_date: Date object for new year
        existing_years: List of dicts with 'start_date' and 'end_date' strings
        
    Returns:
        dict with 'has_overlap' (bool) and 'error' (str) keys
    """
    for year in existing_years:
        existing_start = datetime.strptime(year['start_date'], "%Y-%m-%d").date()
        existing_end = datetime.strptime(year['end_date'], "%Y-%m-%d").date()
        
        # Check if dates overlap
        if start_date < existing_end and end_date > existing_start:
            return {
                "has_overlap": True,
                "error": "Academic year dates overlap with existing academic year"
            }
    
    return {"has_overlap": False, "error": None}


def generate_academic_year_name(start_date, end_date) -> str:
    """
    Generate academic year name in format: YYYY/YYYY
    
    Args:
        start_date: Date object
        end_date: Date object
        
    Returns:
        Formatted academic year name
    """
    start_year = start_date.strftime("%Y")
    end_year = end_date.strftime("%Y")
    return f"{start_year}/{end_year}"


def validate_academic_year_update(
    year_id: str,
    name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current: Optional[bool] = None,
    status: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate academic year update data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not year_id:
        return {"valid": False, "error": "Year ID is required"}
    
    update_data = {}
    
    # Validate name if provided
    if name is not None:
        if not name.strip():
            return {"valid": False, "error": "Name cannot be empty"}
        update_data["name"] = name
    
    # Validate dates if provided
    if start_date or end_date:
        if start_date and not validate_date_format(start_date):
            return {"valid": False, "error": "Invalid start date format"}
        if end_date and not validate_date_format(end_date):
            return {"valid": False, "error": "Invalid end date format"}
        
        if start_date:
            update_data["start_date"] = datetime.strptime(start_date, "%Y-%m-%d").date()
        if end_date:
            update_data["end_date"] = datetime.strptime(end_date, "%Y-%m-%d").date()
    
    # Validate current flag
    if current is not None:
        update_data["current"] = bool(current)
    
    # Validate status
    if status is not None:
        if status not in ["active", "inactive", "archived"]:
            return {"valid": False, "error": "Invalid status value"}
        update_data["status"] = status
    
    return {
        "valid": True,
        "data": update_data,
        "error": None
    }


def can_delete_academic_year(is_current: bool, has_enrollments: bool = False) -> Dict[str, Any]:
    """
    Check if academic year can be deleted
    
    Args:
        is_current: Whether the year is marked as current
        has_enrollments: Whether the year has student enrollments
        
    Returns:
        dict with 'can_delete' (bool) and 'reason' (str) keys
    """
    if is_current:
        return {
            "can_delete": False,
            "reason": "Cannot delete current academic year"
        }
    
    if has_enrollments:
        return {
            "can_delete": False,
            "reason": "Cannot delete academic year with student enrollments"
        }
    
    return {"can_delete": True, "reason": None}

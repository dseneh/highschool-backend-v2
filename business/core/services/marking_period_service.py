"""
Marking Period Business Logic

Pure Python business logic for marking periods - no Django dependencies.
"""

from datetime import datetime
from typing import Dict, Any, Optional


def validate_marking_period_creation(
    name: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    short_name: Optional[str] = None,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate marking period creation data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not name:
        return {"valid": False, "error": "Marking period name is required"}
    
    if not name.strip():
        return {"valid": False, "error": "Marking period name cannot be empty"}
    
    if not start_date:
        return {"valid": False, "error": "Start date is required"}
    
    if not end_date:
        return {"valid": False, "error": "End date is required"}
    
    # Validate and parse dates
    try:
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError:
        return {"valid": False, "error": "Invalid start date format. Use YYYY-MM-DD"}
    
    try:
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return {"valid": False, "error": "Invalid end date format. Use YYYY-MM-DD"}
    
    # Validate date range
    if start_date_obj >= end_date_obj:
        return {"valid": False, "error": "Start date must be before end date"}
    
    return {
        "valid": True,
        "data": {
            "name": name.strip(),
            "short_name": short_name.strip() if short_name else "",
            "description": description.strip() if description else None,
            "start_date": start_date_obj,
            "end_date": end_date_obj,
        },
        "error": None
    }


def validate_marking_period_dates_in_semester(
    start_date,
    end_date,
    semester_start_date,
    semester_end_date
) -> Dict[str, Any]:
    """
    Validate that marking period dates fall within semester dates
    
    Args:
        start_date: Marking period start date object
        end_date: Marking period end date object
        semester_start_date: Semester start date object
        semester_end_date: Semester end date object
        
    Returns:
        dict with 'valid' (bool) and 'error' (str) keys
    """
    if start_date < semester_start_date or end_date > semester_end_date:
        return {
            "valid": False,
            "error": f"Marking period dates must be within semester dates ({semester_start_date} to {semester_end_date})"
        }
    
    return {"valid": True, "error": None}


def validate_marking_period_update(
    marking_period_id: str,
    name: Optional[str] = None,
    short_name: Optional[str] = None,
    description: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    active: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Validate marking period update data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not marking_period_id:
        return {"valid": False, "error": "Marking period ID is required"}
    
    update_data = {}
    
    # Validate name if provided
    if name is not None:
        if not name.strip():
            return {"valid": False, "error": "Name cannot be empty"}
        update_data["name"] = name.strip()
    
    # Validate short name if provided
    if short_name is not None:
        update_data["short_name"] = short_name.strip() if short_name else ""
    
    # Validate description if provided
    if description is not None:
        update_data["description"] = description.strip() if description else None
    
    # Validate dates if provided
    if start_date:
        try:
            update_data["start_date"] = datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError:
            return {"valid": False, "error": "Invalid start date format"}
    
    if end_date:
        try:
            update_data["end_date"] = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return {"valid": False, "error": "Invalid end date format"}
    
    # Validate active flag if provided
    if active is not None:
        update_data["active"] = bool(active)
    
    return {
        "valid": True,
        "data": update_data,
        "error": None
    }

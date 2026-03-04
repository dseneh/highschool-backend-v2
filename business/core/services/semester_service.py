"""
Semester Business Logic

Pure Python business logic for semesters - no Django dependencies.
"""

from datetime import datetime
from typing import Dict, Any, Optional


def validate_semester_creation(
    name: Optional[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate semester creation data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not name:
        return {"valid": False, "error": "Semester name is required"}
    
    if not name.strip():
        return {"valid": False, "error": "Semester name cannot be empty"}
    
    data = {"name": name.strip()}
    
    # Validate dates if provided
    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            data["start_date"] = start_date_obj
        except ValueError:
            return {"valid": False, "error": "Invalid start date format. Use YYYY-MM-DD"}
    
    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            data["end_date"] = end_date_obj
        except ValueError:
            return {"valid": False, "error": "Invalid end date format. Use YYYY-MM-DD"}
    
    # Validate date range if both provided
    if start_date and end_date:
        if data["start_date"] >= data["end_date"]:
            return {"valid": False, "error": "Start date must be before end date"}
    
    return {
        "valid": True,
        "data": data,
        "error": None
    }


def validate_semester_update(
    semester_id: str,
    name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    active: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Validate semester update data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not semester_id:
        return {"valid": False, "error": "Semester ID is required"}
    
    update_data = {}
    
    # Validate name if provided
    if name is not None:
        if not name.strip():
            return {"valid": False, "error": "Name cannot be empty"}
        update_data["name"] = name.strip()
    
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

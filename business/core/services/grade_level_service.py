"""
Grade Level Business Logic

Pure Python business logic for grade levels - no Django dependencies.
"""

from typing import Dict, Any, Optional


def validate_grade_level_creation(
    name: Optional[str],
    short_name: Optional[str] = None,
    level: Optional[int] = None,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate grade level creation data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not name:
        return {"valid": False, "error": "Grade level name is required"}
    
    if not name.strip():
        return {"valid": False, "error": "Grade level name cannot be empty"}
    
    if len(name) > 100:
        return {"valid": False, "error": "Grade level name too long (max 100 characters)"}
    
    # Validate level if provided
    if level is not None:
        level_result = validate_grade_level_number(level)
        if not level_result["valid"]:
            return level_result
    
    return {
        "valid": True,
        "data": {
            "name": name.strip(),
            "short_name": short_name.strip() if short_name else None,
            "level": level,
            "description": description.strip() if description else None,
        },
        "error": None
    }


def validate_grade_level_number(level: int) -> Dict[str, Any]:
    """
    Validate grade level number (1-20)
    
    Args:
        level: Grade level number
        
    Returns:
        dict with 'valid' (bool) and 'error' (str) keys
    """
    try:
        level_int = int(level)
    except (ValueError, TypeError):
        return {"valid": False, "error": "Level must be a number"}
    
    if level_int < 1:
        return {"valid": False, "error": "Level must be at least 1"}
    
    if level_int > 20:
        return {"valid": False, "error": "Level cannot exceed 20"}
    
    return {"valid": True, "error": None}


def validate_grade_level_update(
    grade_level_id: str,
    name: Optional[str] = None,
    short_name: Optional[str] = None,
    level: Optional[int] = None,
    description: Optional[str] = None,
    active: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Validate grade level update data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not grade_level_id:
        return {"valid": False, "error": "Grade level ID is required"}
    
    update_data = {}
    
    # Validate name if provided
    if name is not None:
        if not name.strip():
            return {"valid": False, "error": "Name cannot be empty"}
        if len(name) > 100:
            return {"valid": False, "error": "Name too long (max 100 characters)"}
        update_data["name"] = name.strip()
    
    # Validate short name if provided
    if short_name is not None:
        update_data["short_name"] = short_name.strip() if short_name else None
    
    # Validate level if provided
    if level is not None:
        level_result = validate_grade_level_number(level)
        if not level_result["valid"]:
            return level_result
        update_data["level"] = level
    
    # Validate description if provided
    if description is not None:
        update_data["description"] = description.strip() if description else None
    
    # Validate active flag if provided
    if active is not None:
        update_data["active"] = bool(active)
    
    return {
        "valid": True,
        "data": update_data,
        "error": None
    }


def can_delete_grade_level(has_students: bool = False, has_sections: bool = False) -> Dict[str, Any]:
    """
    Check if grade level can be deleted
    
    Args:
        has_students: Whether the grade level has enrolled students
        has_sections: Whether the grade level has sections
        
    Returns:
        dict with 'can_delete' (bool) and 'reason' (str) keys
    """
    if has_students:
        return {
            "can_delete": False,
            "reason": "Cannot delete grade level with enrolled students"
        }
    
    if has_sections:
        return {
            "can_delete": False,
            "reason": "Cannot delete grade level with sections. Delete sections first."
        }
    
    return {"can_delete": True, "reason": None}

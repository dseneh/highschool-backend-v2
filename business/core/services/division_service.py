"""
Division Business Logic

Pure Python business logic for divisions - no Django dependencies.
"""

from typing import Dict, Any, Optional


def validate_division_creation(
    name: Optional[str],
    description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate division creation data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not name:
        return {"valid": False, "error": "Division name is required"}
    
    if not name.strip():
        return {"valid": False, "error": "Division name cannot be empty"}
    
    if len(name) > 100:
        return {"valid": False, "error": "Division name too long (max 100 characters)"}
    
    return {
        "valid": True,
        "data": {
            "name": name.strip(),
            "description": description.strip() if description else None,
        },
        "error": None
    }


def validate_division_update(
    division_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    active: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Validate division update data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not division_id:
        return {"valid": False, "error": "Division ID is required"}
    
    update_data = {}
    
    # Validate name if provided
    if name is not None:
        if not name.strip():
            return {"valid": False, "error": "Name cannot be empty"}
        if len(name) > 100:
            return {"valid": False, "error": "Name too long (max 100 characters)"}
        update_data["name"] = name.strip()
    
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


def can_delete_division(has_grade_levels: bool = False) -> Dict[str, Any]:
    """
    Check if division can be deleted
    
    Args:
        has_grade_levels: Whether the division has associated grade levels
        
    Returns:
        dict with 'can_delete' (bool) and 'reason' (str) keys
    """
    if has_grade_levels:
        return {
            "can_delete": False,
            "reason": "Cannot delete division with associated grade levels"
        }
    
    return {"can_delete": True, "reason": None}

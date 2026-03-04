"""
Section Business Logic

Pure Python business logic for sections - no Django dependencies.
"""

from typing import Dict, Any, Optional


def validate_section_creation(
    name: Optional[str],
    max_capacity: Optional[int] = None,
    description: Optional[str] = None,
    room_number: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate section creation data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not name:
        return {"valid": False, "error": "Section name is required"}
    
    if not name.strip():
        return {"valid": False, "error": "Section name cannot be empty"}
    
    if len(name) > 100:
        return {"valid": False, "error": "Section name too long (max 100 characters)"}
    
    # Validate max_capacity if provided
    if max_capacity is not None:
        capacity_result = validate_section_capacity(max_capacity)
        if not capacity_result["valid"]:
            return capacity_result
    
    return {
        "valid": True,
        "data": {
            "name": name.strip(),
            "max_capacity": max_capacity,
            "description": description.strip() if description else None,
            "room_number": room_number.strip() if room_number else None,
        },
        "error": None
    }


def validate_section_capacity(capacity: int) -> Dict[str, Any]:
    """
    Validate section capacity (1-1000)
    
    Args:
        capacity: Section capacity
        
    Returns:
        dict with 'valid' (bool) and 'error' (str) keys
    """
    try:
        capacity_int = int(capacity)
    except (ValueError, TypeError):
        return {"valid": False, "error": "Capacity must be a number"}
    
    if capacity_int < 1:
        return {"valid": False, "error": "Capacity must be at least 1"}
    
    if capacity_int > 1000:
        return {"valid": False, "error": "Capacity cannot exceed 1000"}
    
    return {"valid": True, "error": None}


def validate_section_update(
    section_id: str,
    name: Optional[str] = None,
    max_capacity: Optional[int] = None,
    description: Optional[str] = None,
    room_number: Optional[str] = None,
    active: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Validate section update data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not section_id:
        return {"valid": False, "error": "Section ID is required"}
    
    update_data = {}
    
    # Validate name if provided
    if name is not None:
        if not name.strip():
            return {"valid": False, "error": "Name cannot be empty"}
        if len(name) > 100:
            return {"valid": False, "error": "Name too long (max 100 characters)"}
        update_data["name"] = name.strip()

    # Validate max_capacity if provided
    if max_capacity is not None:
        capacity_result = validate_section_capacity(max_capacity)
        if not capacity_result["valid"]:
            return capacity_result
        update_data["max_capacity"] = max_capacity
    
    # Validate description if provided
    if description is not None:
        update_data["description"] = description.strip() if description else None
    
    # Validate room number if provided
    if room_number is not None:
        update_data["room_number"] = room_number.strip() if room_number else None
    
    # Validate active flag if provided
    if active is not None:
        update_data["active"] = bool(active)
    
    return {
        "valid": True,
        "data": update_data,
        "error": None
    }


def can_delete_section(has_enrollments: bool = False) -> Dict[str, Any]:
    """
    Check if section can be deleted
    
    Args:
        has_enrollments: Whether the section has enrolled students
        
    Returns:
        dict with 'can_delete' (bool), 'should_deactivate' (bool), and 'reason' (str) keys
    """
    if has_enrollments:
        return {
            "can_delete": False,
            "should_deactivate": True,
            "reason": "Cannot delete section with enrolled students. Section has been deactivated."
        }
    
    return {"can_delete": True, "should_deactivate": False, "reason": None}

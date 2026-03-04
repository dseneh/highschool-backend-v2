"""
Subject Business Logic

Pure Python business logic for subjects - no Django dependencies.
"""

from typing import Dict, Any, Optional


def validate_subject_creation(
    name: Optional[str],
    code: Optional[str] = None,
    credits: Optional[float] = None,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate subject creation data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not name:
        return {"valid": False, "error": "Subject name is required"}
    
    if not name.strip():
        return {"valid": False, "error": "Subject name cannot be empty"}
    
    if len(name) > 200:
        return {"valid": False, "error": "Subject name too long (max 200 characters)"}
    
    # Validate credits if provided
    if credits is not None:
        credits_result = validate_subject_credits(credits)
        if not credits_result["valid"]:
            return credits_result
    
    return {
        "valid": True,
        "data": {
            "name": name.strip(),
            "code": code.strip() if code else None,
            "credits": credits,
            "description": description.strip() if description else None,
        },
        "error": None
    }


def validate_subject_credits(credits: float) -> Dict[str, Any]:
    """
    Validate subject credits (0-10)
    
    Args:
        credits: Subject credit value
        
    Returns:
        dict with 'valid' (bool) and 'error' (str) keys
    """
    try:
        credits_float = float(credits)
    except (ValueError, TypeError):
        return {"valid": False, "error": "Credits must be a number"}
    
    if credits_float < 0:
        return {"valid": False, "error": "Credits cannot be negative"}
    
    if credits_float > 10:
        return {"valid": False, "error": "Credits cannot exceed 10"}
    
    return {"valid": True, "error": None}


def validate_subject_update(
    subject_id: str,
    name: Optional[str] = None,
    code: Optional[str] = None,
    credits: Optional[float] = None,
    description: Optional[str] = None,
    active: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Validate subject update data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not subject_id:
        return {"valid": False, "error": "Subject ID is required"}
    
    update_data = {}
    
    # Validate name if provided
    if name is not None:
        if not name.strip():
            return {"valid": False, "error": "Name cannot be empty"}
        if len(name) > 200:
            return {"valid": False, "error": "Name too long (max 200 characters)"}
        update_data["name"] = name.strip()
    
    # Validate code if provided
    if code is not None:
        update_data["code"] = code.strip() if code else None
    
    # Validate credits if provided
    if credits is not None:
        credits_result = validate_subject_credits(credits)
        if not credits_result["valid"]:
            return credits_result
        update_data["credits"] = credits
    
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


def can_delete_subject(has_gradebooks: bool = False, has_grades: bool = False) -> Dict[str, Any]:
    """
    Check if subject can be deleted
    
    Args:
        has_gradebooks: Whether the subject has gradebooks
        has_grades: Whether the subject has grades assigned
        
    Returns:
        dict with 'can_delete' (bool), 'should_deactivate' (bool), and 'reason' (str) keys
    """
    if has_grades:
        return {
            "can_delete": False,
            "should_deactivate": True,
            "reason": "Subject has associated grades. It has been deactivated instead of deletion."
        }
    
    if has_gradebooks:
        return {
            "can_delete": False,
            "should_deactivate": True,
            "reason": "Subject has gradebooks. It has been deactivated instead of deletion."
        }
    
    return {"can_delete": True, "should_deactivate": False, "reason": None}

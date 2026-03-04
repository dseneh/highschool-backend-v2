"""
School Business Logic

Pure Python business logic for schools - no Django dependencies.
"""

import re
from typing import Dict, Any, Optional


def validate_school_creation(
    name: Optional[str],
    country: Optional[str],
    workspace: Optional[str],
    short_name: Optional[str] = None,
    email: Optional[str] = None,
    website: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate creation data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not name:
        return {"valid": False, "error": "Name is required"}
    
    if not name.strip():
        return {"valid": False, "error": "Name cannot be empty"}
    
    if not country:
        return {"valid": False, "error": "Country is required"}
    
    if not workspace:
        return {"valid": False, "error": "Workspace is required"}
    
    # Validate workspace format
    workspace_result = validate_workspace_format(workspace)
    if not workspace_result["valid"]:
        return workspace_result
    
    # Validate email if provided
    if email:
        email_result = validate_email_format(email)
        if not email_result["valid"]:
            return email_result
    
    # Validate website if provided
    if website:
        website_result = validate_url_format(website)
        if not website_result["valid"]:
            return website_result
    
    return {
        "valid": True,
        "data": {
            "name": name.strip(),
            "short_name": short_name.strip() if short_name else None,
            "country": country.strip(),
            "workspace": workspace.strip().lower(),
            "email": email.strip().lower() if email else None,
            "website": website.strip() if website else None,
        },
        "error": None
    }


def validate_workspace_format(workspace: str) -> Dict[str, Any]:
    """
    Validate workspace format
    - 3-50 characters
    - Lowercase letters, numbers, hyphens
    - Must start with a letter
    - Cannot have consecutive hyphens
    
    Returns:
        dict with 'valid' (bool) and 'error' (str) keys
    """
    if not workspace:
        return {"valid": False, "error": "Workspace is required"}
    
    workspace = workspace.strip().lower()
    
    if len(workspace) < 3:
        return {"valid": False, "error": "Workspace must be at least 3 characters"}
    
    if len(workspace) > 50:
        return {"valid": False, "error": "Workspace must be at most 50 characters"}
    
    # Must start with a letter
    if not workspace[0].isalpha():
        return {"valid": False, "error": "Workspace must start with a letter"}
    
    # Only lowercase letters, numbers, and hyphens
    if not re.match(r'^[a-z][a-z0-9-]*$', workspace):
        return {"valid": False, "error": "Workspace can only contain lowercase letters, numbers, and hyphens"}
    
    # No consecutive hyphens
    if '--' in workspace:
        return {"valid": False, "error": "Workspace cannot contain consecutive hyphens"}
    
    # Cannot end with hyphen
    if workspace.endswith('-'):
        return {"valid": False, "error": "Workspace cannot end with a hyphen"}
    
    return {"valid": True, "error": None}


def validate_email_format(email: str) -> Dict[str, Any]:
    """
    Validate email format using basic regex
    
    Returns:
        dict with 'valid' (bool) and 'error' (str) keys
    """
    if not email:
        return {"valid": True, "error": None}
    
    email = email.strip()
    
    # Basic email regex
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(pattern, email):
        return {"valid": False, "error": "Invalid email format"}
    
    return {"valid": True, "error": None}


def validate_url_format(url: str) -> Dict[str, Any]:
    """
    Validate URL format
    
    Returns:
        dict with 'valid' (bool) and 'error' (str) keys
    """
    if not url:
        return {"valid": True, "error": None}
    
    url = url.strip()
    
    # Basic URL validation
    pattern = r'^https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)$'
    
    if not re.match(pattern, url):
        return {"valid": False, "error": "Invalid URL format"}
    
    return {"valid": True, "error": None}


def validate_school_update(
    school_id: str,
    name: Optional[str] = None,
    short_name: Optional[str] = None,
    country: Optional[str] = None,
    workspace: Optional[str] = None,
    email: Optional[str] = None,
    website: Optional[str] = None,
    active: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Validate school update data
    
    Returns:
        dict with 'valid' (bool), 'data' (dict), and 'error' (str) keys
    """
    if not school_id:
        return {"valid": False, "error": "School ID is required"}
    
    update_data = {}
    
    # Validate name if provided
    if name is not None:
        if not name.strip():
            return {"valid": False, "error": "Name cannot be empty"}
        update_data["name"] = name.strip()
    
    # Validate short name if provided
    if short_name is not None:
        update_data["short_name"] = short_name.strip() if short_name else None
    
    # Validate country if provided
    if country is not None:
        if not country.strip():
            return {"valid": False, "error": "Country cannot be empty"}
        update_data["country"] = country.strip()
    
    # Validate workspace if provided
    if workspace is not None:
        workspace_result = validate_workspace_format(workspace)
        if not workspace_result["valid"]:
            return workspace_result
        update_data["workspace"] = workspace.strip().lower()
    
    # Validate email if provided
    if email is not None:
        email_result = validate_email_format(email)
        if not email_result["valid"]:
            return email_result
        update_data["email"] = email.strip().lower() if email else None
    
    # Validate website if provided
    if website is not None:
        website_result = validate_url_format(website)
        if not website_result["valid"]:
            return website_result
        update_data["website"] = website.strip() if website else None
    
    # Validate active flag if provided
    if active is not None:
        update_data["active"] = bool(active)
    
    return {
        "valid": True,
        "data": update_data,
        "error": None
    }

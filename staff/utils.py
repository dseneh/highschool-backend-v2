"""Utility functions for staff app"""


def filter_allowed_fields(data, allowed_fields):
    """
    Filter data dictionary to only include allowed fields for security.
    
    Args:
        data: Dictionary of field values
        allowed_fields: List of allowed field names
        
    Returns:
        dict: Filtered dictionary containing only allowed fields
    """
    return {key: value for key, value in data.items() if key in allowed_fields}



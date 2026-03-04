"""
Fee Service - Pure Business Logic

This module contains all business logic for fees (general and section fees).
NO Django dependencies - only pure Python validation and business rules.
"""

from typing import Dict, Optional, Tuple, List
from decimal import Decimal


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_fee_amount(amount: Decimal) -> Optional[str]:
    """
    Validate fee amount
    
    Args:
        amount: Fee amount
        
    Returns:
        Error message or None if valid
    """
    if not amount or amount <= 0:
        return "Amount must be greater than 0"
    
    return None


def validate_student_target(target: str) -> Optional[str]:
    """
    Validate student target type
    
    Args:
        target: Student target type
        
    Returns:
        Error message or None if valid
    """
    valid_targets = ['all', 'new', 'returning']
    
    if target not in valid_targets:
        return f"Invalid student target. Must be one of: {', '.join(valid_targets)}"
    
    return None


def validate_general_fee_creation_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate general fee creation data
    
    Args:
        data: General fee data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    required_fields = ['name', 'amount', 'student_target']
    
    # Check required fields
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Validate amount
    try:
        amount = Decimal(str(data['amount']))
    except (ValueError, TypeError):
        return None, "Invalid amount format"
    
    amount_error = validate_fee_amount(amount)
    if amount_error:
        return None, amount_error
    
    # Validate student target
    target_error = validate_student_target(data['student_target'])
    if target_error:
        return None, target_error
    
    # Build validated data
    validated_data = {
        'name': data['name'].strip(),
        'amount': amount,
        'student_target': data['student_target'],
        'description': data.get('description', '').strip(),
        'active': data.get('active', True),
    }
    
    return validated_data, None


def validate_general_fee_update_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate general fee update data
    
    Args:
        data: Update data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    validated_data = {}
    
    # Validate amount if provided
    if 'amount' in data:
        try:
            amount = Decimal(str(data['amount']))
        except (ValueError, TypeError):
            return None, "Invalid amount format"
        
        amount_error = validate_fee_amount(amount)
        if amount_error:
            return None, amount_error
        
        validated_data['amount'] = amount
    
    # Validate student target if provided
    if 'student_target' in data:
        target_error = validate_student_target(data['student_target'])
        if target_error:
            return None, target_error
        validated_data['student_target'] = data['student_target']
    
    # Copy other allowed fields
    if 'name' in data:
        validated_data['name'] = data['name'].strip()
    
    if 'description' in data:
        validated_data['description'] = data['description'].strip()
    
    if 'active' in data:
        validated_data['active'] = bool(data['active'])
    
    return validated_data, None


def validate_section_fee_creation_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate section fee creation data
    
    Args:
        data: Section fee data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    required_fields = ['section_id', 'general_fee_id', 'amount']
    
    # Check required fields
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Validate amount
    try:
        amount = Decimal(str(data['amount']))
    except (ValueError, TypeError):
        return None, "Invalid amount format"
    
    amount_error = validate_fee_amount(amount)
    if amount_error:
        return None, amount_error
    
    # Build validated data
    validated_data = {
        'section_id': data['section_id'],
        'general_fee_id': data['general_fee_id'],
        'amount': amount,
        'description': data.get('description', '').strip(),
    }
    
    return validated_data, None


def validate_section_fee_update_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate section fee update data
    
    Args:
        data: Update data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    validated_data = {}
    
    # Validate amount if provided
    if 'amount' in data:
        try:
            amount = Decimal(str(data['amount']))
        except (ValueError, TypeError):
            return None, "Invalid amount format"
        
        amount_error = validate_fee_amount(amount)
        if amount_error:
            return None, amount_error
        
        validated_data['amount'] = amount
    
    # Copy other allowed fields
    if 'description' in data:
        validated_data['description'] = data['description'].strip()
    
    if 'section_id' in data:
        validated_data['section_id'] = data['section_id']
    
    if 'general_fee_id' in data:
        validated_data['general_fee_id'] = data['general_fee_id']
    
    return validated_data, None


# =============================================================================
# BUSINESS LOGIC FUNCTIONS
# =============================================================================

def can_delete_general_fee(section_fee_count: int) -> Tuple[bool, Optional[str]]:
    """
    Check if general fee can be deleted
    
    Args:
        section_fee_count: Number of section fees using this general fee
        
    Returns:
        Tuple of (can_delete, error_message)
    """
    if section_fee_count > 0:
        return False, f"Cannot delete general fee. It is being used by {section_fee_count} section(s)."
    
    return True, None


def prepare_fee_data_for_sections(fee_data: dict, section_ids: List[str]) -> List[dict]:
    """
    Prepare fee data for multiple sections
    
    Args:
        fee_data: General fee data
        section_ids: List of section IDs to apply fee to
        
    Returns:
        List of section fee data dictionaries
    """
    section_fees_data = []
    
    for section_id in section_ids:
        section_fees_data.append({
            'section_id': section_id,
            'general_fee_id': fee_data.get('id'),
            'amount': fee_data['amount'],
            'description': fee_data.get('description', ''),
        })
    
    return section_fees_data


def should_apply_to_all_sections(apply_flag: bool, section_ids: Optional[List[str]] = None) -> bool:
    """
    Determine if fee should be applied to all sections
    
    Args:
        apply_flag: Apply to all sections flag
        section_ids: List of specific section IDs (optional)
        
    Returns:
        True if should apply to all sections
    """
    if section_ids:
        return False  # Specific sections provided
    
    return bool(apply_flag)


def get_fee_sorting_fields(ordering: str = '-created_at') -> str:
    """
    Validate and return sorting fields for fees
    
    Args:
        ordering: Requested ordering string
        
    Returns:
        Valid ordering string
    """
    valid_fields = ['name', 'amount', 'created_at', 'updated_at', 'student_target', 'active']
    
    # Extract field name (remove - prefix if present)
    field = ordering.lstrip('-')
    
    if field not in valid_fields:
        return '-created_at'  # Default
    
    return ordering

"""
Supporting Entities Service - Pure Business Logic

This module contains business logic for supporting finance entities:
- Bank Accounts
- Payment Methods  
- Currencies
- Transaction Types

NO Django dependencies - only pure Python validation and business rules.
"""

from typing import Dict, Optional, Tuple
from decimal import Decimal


# =============================================================================
# BANK ACCOUNT VALIDATION
# =============================================================================

def validate_bank_account_creation_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate bank account creation data
    
    Args:
        data: Bank account data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    required_fields = ['name', 'number']
    
    # Check required fields
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Validate account number format
    number = data['number'].strip()
    if len(number) < 5:
        return None, "Account number must be at least 5 characters"
    
    # Build validated data
    validated_data = {
        'name': data['name'].strip(),
        'number': number,
        'bank_number': data.get('bank_number', '').strip(),
        'description': data.get('description', '').strip(),
    }
    
    return validated_data, None


def validate_bank_account_update_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate bank account update data
    
    Args:
        data: Update data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    validated_data = {}
    
    # Validate account number if provided
    if 'number' in data:
        number = data['number'].strip()
        if len(number) < 5:
            return None, "Account number must be at least 5 characters"
        validated_data['number'] = number
    
    # Copy other allowed fields
    if 'name' in data:
        validated_data['name'] = data['name'].strip()
    
    if 'bank_number' in data:
        validated_data['bank_number'] = data['bank_number'].strip()
    
    if 'description' in data:
        validated_data['description'] = data['description'].strip()
    
    return validated_data, None


def can_delete_bank_account(transaction_count: int) -> Tuple[bool, Optional[str]]:
    """
    Check if bank account can be deleted
    
    Args:
        transaction_count: Number of transactions using this account
        
    Returns:
        Tuple of (can_delete, error_message)
    """
    if transaction_count > 0:
        return False, f"Cannot delete bank account. It has {transaction_count} transaction(s)."
    
    return True, None


# =============================================================================
# PAYMENT METHOD VALIDATION
# =============================================================================

def validate_payment_method_creation_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate payment method creation data
    
    Args:
        data: Payment method data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    required_fields = ['name']
    
    # Check required fields
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Build validated data
    validated_data = {
        'name': data['name'].strip(),
        'description': data.get('description', '').strip(),
        'active': data.get('active', True),
    }
    
    return validated_data, None


def validate_payment_method_update_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate payment method update data
    
    Args:
        data: Update data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    validated_data = {}
    
    # Copy allowed fields
    if 'name' in data:
        validated_data['name'] = data['name'].strip()
    
    if 'description' in data:
        validated_data['description'] = data['description'].strip()
    
    if 'active' in data:
        validated_data['active'] = bool(data['active'])
    
    return validated_data, None


# =============================================================================
# CURRENCY VALIDATION
# =============================================================================

def validate_currency_creation_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate currency creation data
    
    Args:
        data: Currency data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    required_fields = ['code', 'name', 'symbol']
    
    # Check required fields
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Validate currency code format (should be 3 characters)
    code = data['code'].strip().upper()
    if len(code) != 3:
        return None, "Currency code must be 3 characters (e.g., USD, EUR, GHS)"
    
    # Build validated data
    validated_data = {
        'code': code,
        'name': data['name'].strip(),
        'symbol': data['symbol'].strip(),
        'is_default': data.get('is_default', False),
    }
    
    return validated_data, None


def validate_currency_update_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate currency update data
    
    Args:
        data: Update data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    validated_data = {}
    
    # Validate currency code if provided
    if 'code' in data:
        code = data['code'].strip().upper()
        if len(code) != 3:
            return None, "Currency code must be 3 characters (e.g., USD, EUR, GHS)"
        validated_data['code'] = code
    
    # Copy other allowed fields
    if 'name' in data:
        validated_data['name'] = data['name'].strip()
    
    if 'symbol' in data:
        validated_data['symbol'] = data['symbol'].strip()
    
    if 'is_default' in data:
        validated_data['is_default'] = bool(data['is_default'])
    
    return validated_data, None


# =============================================================================
# TRANSACTION TYPE VALIDATION
# =============================================================================

def validate_transaction_type_creation_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate transaction type creation data
    
    Args:
        data: Transaction type data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    required_fields = ['name', 'code', 'type']
    
    # Check required fields
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Validate type
    txn_type = data['type'].lower()
    if txn_type not in ['income', 'expense']:
        return None, "Transaction type must be 'income' or 'expense'"
    
    # Build validated data
    validated_data = {
        'name': data['name'].strip(),
        'code': data['code'].strip().upper(),
        'type': txn_type,
        'description': data.get('description', '').strip(),
        'active': data.get('active', True),
    }
    
    return validated_data, None


def validate_transaction_type_update_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate transaction type update data
    
    Args:
        data: Update data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    validated_data = {}
    
    # Validate type if provided
    if 'type' in data:
        txn_type = data['type'].lower()
        if txn_type not in ['income', 'expense']:
            return None, "Transaction type must be 'income' or 'expense'"
        validated_data['type'] = txn_type
    
    # Copy other allowed fields
    if 'name' in data:
        validated_data['name'] = data['name'].strip()
    
    if 'code' in data:
        validated_data['code'] = data['code'].strip().upper()
    
    if 'description' in data:
        validated_data['description'] = data['description'].strip()
    
    if 'active' in data:
        validated_data['active'] = bool(data['active'])
    
    return validated_data, None

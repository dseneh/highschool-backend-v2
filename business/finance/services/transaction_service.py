"""
Transaction Service - Pure Business Logic

This module contains all business logic for financial transactions.
NO Django dependencies - only pure Python validation and business rules.
"""

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from decimal import Decimal


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_amount(amount: Decimal, student_balance: Optional[Decimal] = None, 
                   is_income: bool = False) -> Optional[str]:
    """
    Validate transaction amount
    
    Args:
        amount: Transaction amount
        student_balance: Student's approved balance (for income transactions)
        is_income: Whether this is an income transaction
        
    Returns:
        Error message or None if valid
    """
    if not amount or amount <= 0:
        return "Amount is not valid. Must be greater than 0"
    
    # Additional validation for student balance if it's an income transaction
    if is_income and student_balance is not None:
        if student_balance == 0:
            return "Student has no balance due. Cannot create transaction."
        
        if amount > student_balance:
            return f"Transaction amount exceeds student balance due of {student_balance:,.2f}."
    
    return None


def validate_transaction_date(transaction_date: str) -> Optional[str]:
    """
    Validate transaction date - should not be in the future
    
    Args:
        transaction_date: Date string in YYYY-MM-DD format
        
    Returns:
        Error message or None if valid
    """
    if not transaction_date:
        return None  # Optional field
    
    # Parse date
    try:
        parsed_date = datetime.strptime(transaction_date, "%Y-%m-%d").date()
    except ValueError:
        return "Invalid date format. Use YYYY-MM-DD format."
    
    # Check if date is in the future
    today = date.today()
    if parsed_date > today:
        return "Transaction date cannot be in the future."
    
    return None


def validate_pending_transactions_limit(pending_count: int, limit: int = 2, 
                                       is_update: bool = False) -> Optional[str]:
    """
    Validate that student doesn't exceed pending transactions limit
    
    Args:
        pending_count: Current number of pending transactions for student
        limit: Maximum allowed pending transactions
        is_update: Whether this is an update operation
        
    Returns:
        Error message or None if valid
    """
    if is_update:
        return None  # No limit check for updates
    
    if pending_count >= limit:
        return f"Cannot create more than {limit} pending transactions for a student. Please wait until pending transactions are approved or canceled."
    
    return None


def validate_account_balance(account_balance: Decimal, amount: Decimal, 
                            is_expense: bool) -> Optional[str]:
    """
    Validate account has sufficient balance for expense transactions
    
    Args:
        account_balance: Current account balance
        amount: Transaction amount (negative for expenses)
        is_expense: Whether this is an expense transaction
        
    Returns:
        Error message or None if valid
    """
    if is_expense:
        if float(account_balance) + float(amount) < 0:
            return "Insufficient funds in the account"
    
    return None


def validate_status_transition(current_status: str, new_status: str) -> Optional[str]:
    """
    Validate transaction status transition
    
    Args:
        current_status: Current transaction status
        new_status: New status to transition to
        
    Returns:
        Error message or None if valid
    """
    valid_statuses = ['pending', 'approved', 'canceled']
    
    if new_status not in valid_statuses:
        return f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
    
    # Define allowed transitions
    allowed_transitions = {
        'pending': ['approved', 'canceled'],
        'approved': [],  # Cannot change approved transactions
        'canceled': []   # Cannot change canceled transactions
    }
    
    if current_status in ['approved', 'canceled']:
        return f"Cannot change status of {current_status} transaction"
    
    if new_status not in allowed_transitions.get(current_status, []):
        return f"Cannot transition from {current_status} to {new_status}"
    
    return None


def validate_transaction_creation_data(data: dict) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate transaction creation data
    
    Args:
        data: Transaction data dictionary
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    required_fields = ['amount', 'type_id', 'payment_method_id', 'account_id', 'date']
    
    # Check required fields
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return None, f"Missing required fields: {', '.join(missing_fields)}"
    
    # Validate amount
    try:
        amount = Decimal(str(data['amount']))
    except (ValueError, TypeError):
        return None, "Invalid amount format"
    
    amount_error = validate_amount(amount)
    if amount_error:
        return None, amount_error
    
    # Validate date
    date_error = validate_transaction_date(data.get('date'))
    if date_error:
        return None, date_error
    
    # Build validated data
    validated_data = {
        'amount': amount,
        'type_id': data['type_id'],
        'payment_method_id': data['payment_method_id'],
        'account_id': data['account_id'],
        'date': data['date'],
        'description': data.get('description', ''),
        'reference': data.get('reference', ''),
        'status': data.get('status', 'pending'),
        'student_id': data.get('student_id'),
        'academic_year_id': data.get('academic_year_id'),
        'reference_id': data.get('reference_id'),
    }
    
    return validated_data, None


def validate_transaction_update_data(data: dict, current_status: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    Validate transaction update data
    
    Args:
        data: Update data dictionary
        current_status: Current transaction status
        
    Returns:
        Tuple of (validated_data, error_message)
    """
    # Cannot update approved or canceled transactions
    if current_status in ['approved', 'canceled']:
        return None, f"Cannot update {current_status} transaction"
    
    validated_data = {}
    
    # Validate amount if provided
    if 'amount' in data:
        try:
            amount = Decimal(str(data['amount']))
        except (ValueError, TypeError):
            return None, "Invalid amount format"
        
        amount_error = validate_amount(amount)
        if amount_error:
            return None, amount_error
        
        validated_data['amount'] = amount
    
    # Validate date if provided
    if 'date' in data:
        date_error = validate_transaction_date(data['date'])
        if date_error:
            return None, date_error
        validated_data['date'] = data['date']
    
    # Copy other allowed fields
    allowed_fields = ['description', 'reference', 'type_id', 'payment_method_id', 
                     'account_id', 'student_id', 'academic_year_id', 'reference_id']
    
    for field in allowed_fields:
        if field in data:
            validated_data[field] = data[field]
    
    return validated_data, None


# =============================================================================
# BUSINESS LOGIC FUNCTIONS
# =============================================================================

def prepare_transaction_data(validated_data: dict, transaction_type_code: str) -> dict:
    """
    Prepare transaction data for database storage
    
    Args:
        validated_data: Validated transaction data
        transaction_type_code: Transaction type ('income' or 'expense')
        
    Returns:
        Prepared data dictionary
    """
    # Convert amount to negative for expenses
    amount = validated_data['amount']
    if transaction_type_code == 'expense' and amount > 0:
        amount = -amount
    
    return {
        'amount': amount,
        'date': validated_data['date'],
        'description': validated_data.get('description', ''),
        'reference': validated_data.get('reference', ''),
        'status': validated_data.get('status', 'pending'),
    }


def calculate_transaction_impact(amount: Decimal, transaction_type: str, 
                                 status: str) -> Decimal:
    """
    Calculate the impact of a transaction on account balance
    
    Args:
        amount: Transaction amount
        transaction_type: 'income' or 'expense'
        status: Transaction status
        
    Returns:
        Impact amount (positive for income, negative for expense)
    """
    if status != 'approved':
        return Decimal('0')
    
    if transaction_type == 'expense':
        return -abs(amount)
    else:
        return abs(amount)


def can_delete_transaction(status: str) -> Tuple[bool, Optional[str]]:
    """
    Check if transaction can be deleted
    
    Args:
        status: Transaction status
        
    Returns:
        Tuple of (can_delete, error_message)
    """
    if status == 'approved':
        return False, "Cannot delete approved transaction. Cancel it first."
    
    return True, None


def build_transaction_query_params(params: dict) -> dict:
    """
    Build query parameters for transaction filtering
    
    Args:
        params: Request query parameters
        
    Returns:
        Dictionary of filter parameters
    """
    filters = {}
    
    # Status filter
    if 'status' in params:
        filters['status'] = params['status']
    
    # Date range filters
    if 'start_date' in params:
        filters['date__gte'] = params['start_date']
    
    if 'end_date' in params:
        filters['date__lte'] = params['end_date']
    
    # Student filter
    if 'student_id' in params:
        filters['student_id'] = params['student_id']
    
    # Account filter
    if 'account_id' in params:
        filters['account_id'] = params['account_id']
    
    # Transaction type filter
    if 'type_id' in params:
        filters['type_id'] = params['type_id']
    
    return filters


def get_sorting_fields(ordering: str = '-updated_at') -> str:
    """
    Validate and return sorting fields
    
    Args:
        ordering: Requested ordering string
        
    Returns:
        Valid ordering string
    """
    valid_fields = ['date', 'amount', 'created_at', 'updated_at', 'status']
    
    # Extract field name (remove - prefix if present)
    field = ordering.lstrip('-')
    
    if field not in valid_fields:
        return '-updated_at'  # Default
    
    return ordering

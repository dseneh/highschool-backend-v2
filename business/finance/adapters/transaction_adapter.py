"""
Transaction Django Adapter - Database Operations

This module handles all Django-specific database operations for transactions.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional, List, Dict
from django.db import transaction as db_transaction
from django.db.models import Q, Sum, Count
from decimal import Decimal

from common.utils import get_object_by_uuid_or_fields
from finance.models import Transaction, BankAccount, TransactionType, PaymentMethod
from academics.models import AcademicYear
from students.models import get_student_model
from business.finance.finance_models import TransactionData
from students.models_backup import Student


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_transaction_to_data(txn) -> TransactionData:
    """Convert Django Transaction model to business data object"""
    return TransactionData(
        id=str(txn.id),
        account_id=str(txn.account_id),
        type_id=str(txn.type_id),
        amount=Decimal(str(txn.amount)),
        date=txn.date.isoformat(),
        description=txn.description or "",
        reference=txn.reference or "",
        status=txn.status,
        student_id=str(txn.student_id) if txn.student_id else None,
        academic_year_id=str(txn.academic_year_id) if txn.academic_year_id else None,
        payment_method_id=str(txn.payment_method_id) if txn.payment_method_id else None,
        reference_id=str(txn.reference_id) if txn.reference_id else None,
    )


def get_bank_account(account_id: str) -> Optional[BankAccount]:
    """Get bank account by ID or number"""
    try:
        return BankAccount.objects.get(
            Q(id=account_id) | Q(number=account_id)
        )
    except BankAccount.DoesNotExist:
        return None


def get_transaction_type(type_id: str) -> Optional[TransactionType]:
    """Get transaction type by ID, name, or code"""
    try:
        return TransactionType.objects.get(
            Q(id=type_id) | Q(name__iexact=type_id) | Q(code__iexact=type_id)
        )
    except TransactionType.DoesNotExist:
        return None


def get_payment_method(method_id: str) -> Optional[PaymentMethod]:
    """Get payment method by ID"""
    try:
        method = PaymentMethod.objects.get(id=method_id)
        return method if method.active else None
    except PaymentMethod.DoesNotExist:
        return None


def get_student(student_id: str) -> Optional[Student]:
    """Get student by ID or ID number"""
    try:
        return Student.objects.get(Q(id=student_id) | Q(id_number=student_id))
    except Student.DoesNotExist:
        return None


def get_academic_year(year_id: str) -> Optional[AcademicYear]:
    """Get academic year by ID"""
    try:
        return AcademicYear.objects.get(id=year_id)
    except AcademicYear.DoesNotExist:
        return None


# =============================================================================
# TRANSACTION DATABASE OPERATIONS
# =============================================================================

@db_transaction.atomic
def create_transaction_in_db(data: dict, account_id: str, type_id: str,
                            payment_method_id: str, student_id: Optional[str] = None,
                            academic_year_id: Optional[str] = None,
                            user=None) -> Optional[Transaction]:
    """
    Create transaction in database
    
    Args:
        data: Prepared transaction data
        account_id: Bank account ID
        type_id: Transaction type ID
        payment_method_id: Payment method ID
        student_id: Student ID (optional)
        academic_year_id: Academic year ID (optional)
        user: User creating the transaction
        
    Returns:
        Created Transaction instance or None if validation fails
    """
    try:
        account = BankAccount.objects.get(id=account_id)
        txn_type = TransactionType.objects.get(id=type_id)
        payment_method = PaymentMethod.objects.get(id=payment_method_id)
        
        student = None
        if student_id:
            student = get_object_by_uuid_or_fields(Student, student_id, ["id", "id_number", "prev_id_number"])
        
        academic_year = None
        if academic_year_id:
            academic_year = AcademicYear.objects.get(id=academic_year_id)
        
        txn = Transaction.objects.create(
            account=account,
            type=txn_type,
            payment_method=payment_method,
            student=student,
            academic_year=academic_year,
            amount=data['amount'],
            date=data['date'],
            description=data.get('description', ''),
            reference=data.get('reference', ''),
            status=data.get('status', 'pending'),
            reference_id=data.get('reference_id'),
            created_by=user,
            updated_by=user,
        )
        
        return txn
    except Exception:
        return None


@db_transaction.atomic
def update_transaction_in_db(transaction_id: str, data: dict, 
                             user=None) -> Optional[Transaction]:
    """
    Update transaction in database
    
    Args:
        transaction_id: Transaction ID
        data: Update data dictionary
        user: User updating the transaction
        
    Returns:
        Updated Transaction instance or None if not found
    """
    try:
        txn = Transaction.objects.get(id=transaction_id)
        
        # Update foreign key fields if provided
        if 'account_id' in data:
            txn.account = BankAccount.objects.get(id=data['account_id'])
        
        if 'type_id' in data:
            txn.type = TransactionType.objects.get(id=data['type_id'])
        
        if 'payment_method_id' in data:
            txn.payment_method = PaymentMethod.objects.get(id=data['payment_method_id'])
        
        if 'student_id' in data:
            txn.student = get_object_by_uuid_or_fields(Student, data['student_id'], ["id", "id_number", "prev_id_number"]) if data['student_id'] else None
        
        if 'academic_year_id' in data:
            txn.academic_year = AcademicYear.objects.get(id=data['academic_year_id']) if data['academic_year_id'] else None
        
        # Update simple fields
        simple_fields = ['amount', 'date', 'description', 'reference', 'status', 'reference_id']
        for field in simple_fields:
            if field in data:
                setattr(txn, field, data[field])
        
        txn.updated_by = user
        txn.save()
        
        return txn
    except Exception:
        return None


@db_transaction.atomic
def update_transaction_status_in_db(transaction_id: str, status: str, 
                                   user=None) -> Optional[Transaction]:
    """
    Update transaction status in database
    
    Args:
        transaction_id: Transaction ID
        status: New status
        user: User updating the transaction
        
    Returns:
        Updated Transaction instance or None if not found
    """
    try:
        txn = Transaction.objects.get(id=transaction_id)
        txn.status = status
        txn.updated_by = user
        txn.save()
        
        return txn
    except Transaction.DoesNotExist:
        return None


def delete_transaction_from_db(transaction_id: str) -> bool:
    """
    Delete transaction from database
    
    Args:
        transaction_id: Transaction ID
        
    Returns:
        True if deleted, False if not found
    """
    try:
        Transaction.objects.get(id=transaction_id).delete()
        return True
    except Transaction.DoesNotExist:
        return False


def delete_transactions_by_reference_from_db(reference_id: str) -> int:
    """
    Delete all transactions with given reference ID
    
    Args:
        reference_id: Reference ID
        
    Returns:
        Number of transactions deleted
    """
    deleted_count, _ = Transaction.objects.filter(reference_id=reference_id).delete()
    return deleted_count


# =============================================================================
# QUERY FUNCTIONS
# =============================================================================

def get_transaction_by_id(transaction_id: str) -> Optional[Transaction]:
    """Get transaction by ID"""
    try:
        return Transaction.objects.select_related(
            'student', 'academic_year', 'account', 'type', 'payment_method'
        ).get(id=transaction_id)
    except Transaction.DoesNotExist:
        return None


def get_student_pending_transactions_count(student_id: str) -> int:
    """Get count of pending transactions for student"""
    return Transaction.objects.filter(
        student_id=student_id,
        status='pending'
    ).count()


def get_student_approved_balance(student_id: str) -> Decimal:
    """
    Get student's approved balance
    This should call the student's method or calculate from approved transactions
    """
    try:
        student = get_object_by_uuid_or_fields(Student, student_id, ["id", "id_number"])
        # Assuming the student model has a method to get approved balance
        if hasattr(student, 'get_approved_balance'):
            return Decimal(str(student.get_approved_balance()))
        return Decimal('0')
    except Student.DoesNotExist:
        return Decimal('0')


def get_account_balance(account_id: str) -> Decimal:
    """Get current balance of bank account"""
    try:
        account = BankAccount.objects.get(id=account_id)
        return Decimal(str(account.balance))
    except BankAccount.DoesNotExist:
        return Decimal('0')


def get_transactions_by_filters(filters: dict,
                                ordering: str = '-updated_at') -> List[Transaction]:
    """
    Get transactions by filters
    
    Args:
        filters: Dictionary of filter parameters
        ordering: Ordering field
        
    Returns:
        List of Transaction instances
    """
    qs = Transaction.objects.select_related(
        'student', 'academic_year', 'account', 'type', 'payment_method'
    ).all()
    
    # Apply filters
    if filters:
        qs = qs.filter(**filters)
    
    return list(qs.order_by(ordering))


@db_transaction.atomic
def create_bulk_transactions_in_db(transactions_data: List[dict], 
                                  user=None) -> List[Transaction]:
    """
    Create multiple transactions in database
    
    Args:
        transactions_data: List of transaction data dictionaries
        user: User creating the transactions
        
    Returns:
        List of created Transaction instances
    """
    transactions = []
    
    for data in transactions_data:
        txn = create_transaction_in_db(
            data=data,
            account_id=data['account_id'],
            type_id=data['type_id'],
            payment_method_id=data['payment_method_id'],
            student_id=data.get('student_id'),
            academic_year_id=data.get('academic_year_id'),
            user=user
        )
        if txn:
            transactions.append(txn)
    
    return transactions

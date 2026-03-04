"""
Supporting Entities Django Adapter - Database Operations

This module handles Django-specific database operations for supporting finance entities:
- Bank Accounts
- Payment Methods
- Currencies
- Transaction Types

Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional, List
from django.db import transaction
from django.db.models import Q
from decimal import Decimal

from finance.models import BankAccount, PaymentMethod, Currency, TransactionType
from business.finance.finance_models import (
    BankAccountData, PaymentMethodData, CurrencyData, TransactionTypeData
)


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_bank_account_to_data(account) -> BankAccountData:
    """Convert Django BankAccount model to business data object"""
    return BankAccountData(
        id=str(account.id),
        number=account.number,
        bank_number=account.bank_number or "",
        name=account.name,
        description=account.description or "",
        balance=Decimal(str(account.balance)) if hasattr(account, 'balance') else None,
    )


def django_payment_method_to_data(method) -> PaymentMethodData:
    """Convert Django PaymentMethod model to business data object"""
    return PaymentMethodData(
        id=str(method.id),
        name=method.name,
        description=method.description or "",
        active=method.active,
    )


def django_currency_to_data(currency) -> CurrencyData:
    """Convert Django Currency model to business data object"""
    return CurrencyData(
        id=str(currency.id),
        code=currency.code,
        name=currency.name,
        symbol=currency.symbol,
        is_default=currency.is_default,
    )


def django_transaction_type_to_data(txn_type) -> TransactionTypeData:
    """Convert Django TransactionType model to business data object"""
    return TransactionTypeData(
        id=str(txn_type.id),
        name=txn_type.name,
        code=txn_type.code,
        type=txn_type.type,
        description=txn_type.description or "",
        active=txn_type.active,
    )


# =============================================================================
# BANK ACCOUNT DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_bank_account_in_db(data: dict, user=None) -> Optional[BankAccount]:
    """
    Create bank account in database
    
    Args:
        data: Validated account data
        user: User creating the account
        
    Returns:
        Created BankAccount instance or None if failed
    """
    try:
        
        account = BankAccount.objects.create(
            name=data['name'],
            number=data['number'],
            bank_number=data.get('bank_number', ''),
            description=data.get('description', ''),
            created_by=user,
            updated_by=user,
        )
        
        return account
    except Exception:
        return None


@transaction.atomic
def update_bank_account_in_db(account_id: str, data: dict, user=None) -> Optional[BankAccount]:
    """
    Update bank account in database
    
    Args:
        account_id: Account ID
        data: Update data dictionary
        user: User updating the account
        
    Returns:
        Updated BankAccount instance or None if not found
    """
    try:
        account = BankAccount.objects.get(id=account_id)
        
        for field, value in data.items():
            if hasattr(account, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(account, field, value)
        
        account.updated_by = user
        account.save()
        
        return account
    except BankAccount.DoesNotExist:
        return None


def delete_bank_account_from_db(account_id: str) -> bool:
    """Delete bank account from database"""
    try:
        BankAccount.objects.get(id=account_id).delete()
        return True
    except BankAccount.DoesNotExist:
        return False


def get_bank_account_by_id(account_id: str) -> Optional[BankAccount]:
    """Get bank account by ID"""
    try:
        return BankAccount.objects.get(id=account_id)
    except BankAccount.DoesNotExist:
        return None


def get_bank_accounts_by_school() -> List[BankAccount]:
    """Get all bank accounts"""
    return list(BankAccount.objects.all())


def get_bank_account_transaction_count(account_id: str) -> int:
    """Get count of transactions for bank account"""
    try:
        account = BankAccount.objects.get(id=account_id)
        return account.transactions.count()
    except BankAccount.DoesNotExist:
        return 0


def check_bank_account_number_exists(number: str, 
                                     exclude_id: Optional[str] = None) -> bool:
    """Check if bank account number already exists"""
    query = Q(number=number)
    if exclude_id:
        query &= ~Q(id=exclude_id)
    return BankAccount.objects.filter(query).exists()


# =============================================================================
# PAYMENT METHOD DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_payment_method_in_db(data: dict, user=None) -> Optional[PaymentMethod]:
    """Create payment method in database"""
    try:
        
        method = PaymentMethod.objects.create(
            name=data['name'],
            description=data.get('description', ''),
            active=data.get('active', True),
            created_by=user,
            updated_by=user,
        )
        
        return method
    except Exception:
        return None


@transaction.atomic
def update_payment_method_in_db(method_id: str, data: dict, user=None) -> Optional[PaymentMethod]:
    """Update payment method in database"""
    try:
        method = PaymentMethod.objects.get(id=method_id)
        
        for field, value in data.items():
            if hasattr(method, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(method, field, value)
        
        method.updated_by = user
        method.save()
        
        return method
    except PaymentMethod.DoesNotExist:
        return None


def delete_payment_method_from_db(method_id: str) -> bool:
    """Delete payment method from database"""
    try:
        PaymentMethod.objects.get(id=method_id).delete()
        return True
    except PaymentMethod.DoesNotExist:
        return False


def get_payment_method_by_id(method_id: str) -> Optional[PaymentMethod]:
    """Get payment method by ID"""
    try:
        return PaymentMethod.objects.get(id=method_id)
    except PaymentMethod.DoesNotExist:
        return None


def get_payment_methods_by_school(active_only: bool = False) -> List[PaymentMethod]:
    """Get all payment methods"""
    qs = PaymentMethod.objects.all()
    if active_only:
        qs = qs.filter(active=True)
    return list(qs)


# =============================================================================
# CURRENCY DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_currency_in_db(data: dict, user=None) -> Optional[Currency]:
    """Create currency in database"""
    try:        
        # If this is set as default, unset other defaults
        if data.get('is_default', False):
            Currency.objects.filter(is_default=True).update(is_default=False)
        
        currency = Currency.objects.create(
            code=data['code'],
            name=data['name'],
            symbol=data['symbol'],
            is_default=data.get('is_default', False),
            created_by=user,
            updated_by=user,
        )
        
        return currency
    except Exception:
        return None


@transaction.atomic
def update_currency_in_db(currency_id: str, data: dict, user=None) -> Optional[Currency]:
    """Update currency in database"""
    try:
        currency = Currency.objects.get(id=currency_id)
        
        # If setting as default, unset other defaults
        if data.get('is_default', False):
            Currency.objects.filter(is_default=True).exclude(id=currency_id).update(is_default=False)
        
        for field, value in data.items():
            if hasattr(currency, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(currency, field, value)
        
        currency.updated_by = user
        currency.save()
        
        return currency
    except Currency.DoesNotExist:
        return None


def delete_currency_from_db(currency_id: str) -> bool:
    """Delete currency from database"""
    try:
        Currency.objects.get(id=currency_id).delete()
        return True
    except Currency.DoesNotExist:
        return False


def get_currency_by_id(currency_id: str) -> Optional[Currency]:
    """Get currency by ID"""
    try:
        return Currency.objects.get(id=currency_id)
    except Currency.DoesNotExist:
        return None


def get_currencies_by_school() -> List[Currency]:
    """Get all currencies"""
    return list(Currency.objects.all())


def check_currency_code_exists(code: str, 
                               exclude_id: Optional[str] = None) -> bool:
    """Check if currency code already exists"""
    query = Q(code__iexact=code)
    if exclude_id:
        query &= ~Q(id=exclude_id)
    return Currency.objects.filter(query).exists()


# =============================================================================
# TRANSACTION TYPE DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_transaction_type_in_db(data: dict, user=None) -> Optional[TransactionType]:
    """Create transaction type in database"""
    try:        
        txn_type = TransactionType.objects.create(
            name=data['name'],
            code=data['code'],
            type=data['type'],
            description=data.get('description', ''),
            active=data.get('active', True),
            created_by=user,
            updated_by=user,
        )
        
        return txn_type
    except Exception:
        return None


@transaction.atomic
def update_transaction_type_in_db(type_id: str, data: dict, user=None) -> Optional[TransactionType]:
    """Update transaction type in database"""
    try:
        txn_type = TransactionType.objects.get(id=type_id)
        
        for field, value in data.items():
            if hasattr(txn_type, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(txn_type, field, value)
        
        txn_type.updated_by = user
        txn_type.save()
        
        return txn_type
    except TransactionType.DoesNotExist:
        return None


def delete_transaction_type_from_db(type_id: str) -> bool:
    """Delete transaction type from database"""
    try:
        TransactionType.objects.get(id=type_id).delete()
        return True
    except TransactionType.DoesNotExist:
        return False


def get_transaction_type_by_id(type_id: str) -> Optional[TransactionType]:
    """Get transaction type by ID"""
    try:
        return TransactionType.objects.get(id=type_id)
    except TransactionType.DoesNotExist:
        return None


def get_transaction_types_by_school(active_only: bool = False) -> List[TransactionType]:
    """Get all transaction types"""
    qs = TransactionType.objects.all()
    if active_only:
        qs = qs.filter(active=True)
    return list(qs)


def check_transaction_type_code_exists(code: str, 
                                       exclude_id: Optional[str] = None) -> bool:
    """Check if transaction type code already exists"""
    query = Q(code__iexact=code)
    if exclude_id:
        query &= ~Q(id=exclude_id)
    return TransactionType.objects.filter(query).exists()

"""
Finance Data Models (DTOs)

Framework-agnostic data structures for finance module.
"""

from dataclasses import dataclass
from typing import Optional
from decimal import Decimal


@dataclass
class BankAccountData:
    """Bank account data transfer object"""
    id: str
    number: str
    bank_number: Optional[str]
    name: str
    description: Optional[str]
    balance: Optional[Decimal] = None


@dataclass
class PaymentMethodData:
    """Payment method data transfer object"""
    id: str
    name: str
    description: Optional[str]
    active: bool


@dataclass
class CurrencyData:
    """Currency data transfer object"""
    id: str
    code: str
    name: str
    symbol: str
    is_default: bool


@dataclass
class TransactionTypeData:
    """Transaction type data transfer object"""
    id: str
    name: str
    code: str
    type: str  # 'income' or 'expense'
    description: Optional[str]
    active: bool


@dataclass
class TransactionData:
    """Transaction data transfer object"""
    id: str
    account_id: str
    type_id: str
    amount: Decimal
    date: str
    description: Optional[str]
    reference: Optional[str]
    status: str
    student_id: Optional[str] = None
    academic_year_id: Optional[str] = None
    payment_method_id: Optional[str] = None
    reference_id: Optional[str] = None


@dataclass
class GeneralFeeData:
    """General fee data transfer object"""
    id: str
    name: str
    amount: Decimal
    student_target: str  # 'all', 'new', 'returning'
    description: Optional[str]
    active: bool


@dataclass
class SectionFeeData:
    """Section fee data transfer object"""
    id: str
    section_id: str
    general_fee_id: str
    amount: Decimal
    description: Optional[str]


@dataclass
class PaymentInstallmentData:
    """Payment installment data transfer object"""
    id: str
    academic_year_id: str
    name: str
    amount: Decimal
    due_date: str
    sequence: int
    description: Optional[str]

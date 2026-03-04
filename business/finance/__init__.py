"""
Finance Business Logic Module

Framework-agnostic business logic for the finance module.
This provides a clean separation between business rules (services)
and database operations (adapters).

Structure:
- services/: Pure Python business logic (validation, business rules)
- adapters/: Django-specific database operations
- finance_models.py: Data Transfer Objects (DTOs)
"""

from . import services
from . import adapters
from .finance_models import (
    BankAccountData,
    PaymentMethodData,
    CurrencyData,
    TransactionTypeData,
    TransactionData,
    GeneralFeeData,
    SectionFeeData,
    PaymentInstallmentData,
)

__all__ = [
    'services',
    'adapters',
    'BankAccountData',
    'PaymentMethodData',
    'CurrencyData',
    'TransactionTypeData',
    'TransactionData',
    'GeneralFeeData',
    'SectionFeeData',
    'PaymentInstallmentData',
]

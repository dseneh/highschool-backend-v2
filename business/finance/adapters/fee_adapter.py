"""
Fee Django Adapter - Database Operations

This module handles all Django-specific database operations for fees.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional, List
from django.db import transaction
from django.db.models import Q
from decimal import Decimal

from finance.models import GeneralFeeList, SectionFee
from academics.models import Section
from business.finance.finance_models import GeneralFeeData, SectionFeeData


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_general_fee_to_data(fee) -> GeneralFeeData:
    """Convert Django GeneralFeeList model to business data object"""
    return GeneralFeeData(
        id=str(fee.id),
        name=fee.name,
        amount=Decimal(str(fee.amount)),
        student_target=fee.student_target,
        description=fee.description or "",
        active=fee.active,
    )


def django_section_fee_to_data(fee) -> SectionFeeData:
    """Convert Django SectionFee model to business data object"""
    return SectionFeeData(
        id=str(fee.id),
        section_id=str(fee.section_id),
        general_fee_id=str(fee.general_fee_id),
        amount=Decimal(str(fee.amount)),
        description=fee.description or "",
    )



def get_general_fee_by_id(fee_id: str) -> Optional[GeneralFeeList]:
    """Get general fee by ID"""
    try:
        return GeneralFeeList.objects.get(id=fee_id)
    except GeneralFeeList.DoesNotExist:
        return None


def get_section_fee_by_id(fee_id: str) -> Optional[SectionFee]:
    """Get section fee by ID"""
    try:
        return SectionFee.objects.select_related('section', 'general_fee').get(id=fee_id)
    except SectionFee.DoesNotExist:
        return None


def get_section_by_id(section_id: str) -> Optional[Section]:
    """Get section by ID"""
    try:
        return Section.objects.get(id=section_id)
    except Section.DoesNotExist:
        return None


# =============================================================================
# GENERAL FEE DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_general_fee_in_db(data: dict, user=None) -> Optional[GeneralFeeList]:
    """
    Create general fee in database
    
    Args:
        data: Validated fee data
        user: User creating the fee
        
    Returns:
        Created GeneralFeeList instance or None if failed
    """
    try:
        
        fee = GeneralFeeList.objects.create(
            name=data['name'],
            amount=data['amount'],
            student_target=data['student_target'],
            description=data.get('description', ''),
            active=data.get('active', True),
            created_by=user,
            updated_by=user,
        )
        
        return fee
    except Exception:
        return None


@transaction.atomic
def update_general_fee_in_db(fee_id: str, data: dict, user=None) -> Optional[GeneralFeeList]:
    """
    Update general fee in database
    
    Args:
        fee_id: Fee ID
        data: Update data dictionary
        user: User updating the fee
        
    Returns:
        Updated GeneralFeeList instance or None if not found
    """
    try:
        fee = GeneralFeeList.objects.get(id=fee_id)
        
        # Update fields
        for field, value in data.items():
            if hasattr(fee, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(fee, field, value)
        
        fee.updated_by = user
        fee.save()
        
        return fee
    except GeneralFeeList.DoesNotExist:
        return None


def delete_general_fee_from_db(fee_id: str) -> bool:
    """
    Delete general fee from database
    
    Args:
        fee_id: Fee ID
        
    Returns:
        True if deleted, False if not found
    """
    try:
        GeneralFeeList.objects.get(id=fee_id).delete()
        return True
    except GeneralFeeList.DoesNotExist:
        return False


def get_general_fees_by_school(active_only: bool = False) -> List[GeneralFeeList]:
    """
    Get all general fees
    
    Args:
        active_only: If True, return only active fees
        
    Returns:
        List of GeneralFeeList instances
    """
    qs = GeneralFeeList.objects.all()
    
    if active_only:
        qs = qs.filter(active=True)
    
    return list(qs.only('id', 'name', 'description', 'amount', 'student_target', 'active'))


def get_section_fee_count_for_general_fee(fee_id: str) -> int:
    """Get count of section fees using this general fee"""
    return SectionFee.objects.filter(general_fee_id=fee_id).count()


# =============================================================================
# SECTION FEE DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_section_fee_in_db(data: dict, user=None) -> Optional[SectionFee]:
    """
    Create section fee in database
    
    Args:
        data: Validated section fee data
        user: User creating the fee
        
    Returns:
        Created SectionFee instance or None if failed
    """
    try:
        section = Section.objects.get(id=data['section_id'])
        general_fee = GeneralFeeList.objects.get(id=data['general_fee_id'])
        
        fee = SectionFee.objects.create(
            section=section,
            general_fee=general_fee,
            amount=data['amount'],
            description=data.get('description', ''),
            created_by=user,
            updated_by=user,
        )
        
        return fee
    except Exception:
        return None


@transaction.atomic
def create_or_update_section_fee_in_db(section_id: str, general_fee_id: str, 
                                      data: dict, user=None) -> Optional[SectionFee]:
    """
    Create or update section fee in database
    
    Args:
        section_id: Section ID
        general_fee_id: General fee ID
        data: Section fee data
        user: User creating/updating the fee
        
    Returns:
        Created or updated SectionFee instance
    """
    try:
        section = Section.objects.get(id=section_id)
        general_fee = GeneralFeeList.objects.get(id=general_fee_id)
        
        fee, created = SectionFee.objects.update_or_create(
            section=section,
            general_fee=general_fee,
            defaults={
                'amount': data['amount'],
                'description': data.get('description', ''),
                'updated_by': user,
            }
        )
        
        if created and user:
            fee.created_by = user
            fee.save()
        
        return fee
    except Exception:
        return None


@transaction.atomic
def update_section_fee_in_db(fee_id: str, data: dict, user=None) -> Optional[SectionFee]:
    """
    Update section fee in database
    
    Args:
        fee_id: Fee ID
        data: Update data dictionary
        user: User updating the fee
        
    Returns:
        Updated SectionFee instance or None if not found
    """
    try:
        fee = SectionFee.objects.get(id=fee_id)
        
        # Update foreign keys if provided
        if 'section_id' in data:
            fee.section = Section.objects.get(id=data['section_id'])
        
        if 'general_fee_id' in data:
            fee.general_fee = GeneralFeeList.objects.get(id=data['general_fee_id'])
        
        # Update other fields
        if 'amount' in data:
            fee.amount = data['amount']
        
        if 'description' in data:
            fee.description = data['description']
        
        fee.updated_by = user
        fee.save()
        
        return fee
    except SectionFee.DoesNotExist:
        return None


def delete_section_fee_from_db(fee_id: str) -> bool:
    """
    Delete section fee from database
    
    Args:
        fee_id: Fee ID
        
    Returns:
        True if deleted, False if not found
    """
    try:
        SectionFee.objects.get(id=fee_id).delete()
        return True
    except SectionFee.DoesNotExist:
        return False


def get_section_fees_by_school() -> List[SectionFee]:
    """
    Get all section fees
        
    Returns:
        List of SectionFee instances
    """
    return list(
        SectionFee.objects.select_related('section', 'general_fee')
        .all()
    )


def get_section_fees_by_filters(filters: dict) -> List[SectionFee]:
    """
    Get section fees by filters
    
    Args:
        filters: Dictionary of filter parameters
        
    Returns:
        List of SectionFee instances
    """
    qs = SectionFee.objects.select_related('section', 'general_fee').all()
    
    # Apply filters
    if filters:
        qs = qs.filter(**filters)
    
    return list(qs)


def get_active_sections_by_school() -> List[Section]:
    """
    Get all active sections
        
    Returns:
        List of Section instances
    """
    return list(
        Section.objects.filter(active=True).only('id')
    )


@transaction.atomic
def apply_fee_to_all_sections(general_fee_id: str, amount: Decimal, 
                             user=None) -> List[SectionFee]:
    """
    Apply general fee to all active sections
    
    Args:
        general_fee_id: General fee ID
        amount: Fee amount
        user: User creating the fees
        
    Returns:
        List of created/updated SectionFee instances
    """
    sections = get_active_sections_by_school()
    section_fees = []
    
    for section in sections:
        fee = create_or_update_section_fee_in_db(
            section_id=str(section.id),
            general_fee_id=general_fee_id,
            data={'amount': amount, 'description': ''},
            user=user
        )
        if fee:
            section_fees.append(fee)
    
    return section_fees

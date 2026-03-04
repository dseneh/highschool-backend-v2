"""
Staff Django Adapter - Database Operations

This module handles all Django-specific database operations for staff.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional
from django.db import transaction
from django.db.models import Q

from staff.models import Staff, Position, Department
from business.staff.staff_models import StaffData


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_staff_to_data(staff) -> StaffData:
    """Convert Django Staff model to business data object"""
    return StaffData(
        id=str(staff.id),
        first_name=staff.first_name,
        last_name=staff.last_name,
        middle_name=staff.middle_name or "",
        gender=staff.gender,
        id_number=staff.id_number,
        date_of_birth=staff.date_of_birth.isoformat() if staff.date_of_birth else None,
        email=staff.email or None,
        phone_number=staff.phone_number or "",
        address=staff.address or None,
        city=staff.city or None,
        state=staff.state or None,
        postal_code=staff.postal_code or None,
        country=staff.country or None,
        place_of_birth=staff.place_of_birth or None,
        status=staff.status,
        hire_date=staff.hire_date.isoformat() if staff.hire_date else None,
        position_id=str(staff.position_id) if staff.position_id else None,
        primary_department_id=str(staff.primary_department_id) if staff.primary_department_id else None,
        is_teacher=staff.is_teacher,
        photo=staff.photo.url if staff.photo else None,
        suspension_date=staff.suspension_date.isoformat() if staff.suspension_date else None,
        suspension_reason=staff.suspension_reason,
        termination_date=staff.termination_date.isoformat() if staff.termination_date else None,
        termination_reason=staff.termination_reason,
        user_account_id_number=staff.user_account_id_number if staff.user_account_id_number else None,
    )


# =============================================================================
# STAFF DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_staff_in_db(data: dict, position_id: Optional[str] = None,
                       department_id: Optional[str] = None, user=None) -> Staff:
    """
    Create staff record in database
    
    Args:
        data: Prepared staff data dictionary
        position_id: Position ID (optional)
        department_id: Primary department ID (optional)
        user: User creating the staff
        
    Returns:
        Created Staff instance
    """
    from common.utils import generate_unique_id_number
    from core.models import Tenant
    
    # Get position if provided
    position = None
    if position_id:
        position = Position.objects.filter(id=position_id).first()
    
    # Get department if provided
    department = None
    if department_id:
        department = Department.objects.filter(id=department_id).first()
    
    # Generate ID if not provided
    id_number = data.get('id_number')
    if not id_number:
        id_number = generate_unique_id_number(Staff, Tenant)
    
    # Create staff
    staff = Staff.objects.create(
        id_number=id_number,
        first_name=data['first_name'],
        last_name=data['last_name'],
        middle_name=data.get('middle_name'),
        date_of_birth=data.get('date_of_birth'),
        gender=data['gender'],
        email=data.get('email'),
        phone_number=data.get('phone_number', ''),
        address=data.get('address'),
        city=data.get('city'),
        state=data.get('state'),
        postal_code=data.get('postal_code'),
        country=data.get('country'),
        place_of_birth=data.get('place_of_birth'),
        status=data.get('status', 'active'),
        hire_date=data.get('hire_date'),
        position=position,
        primary_department=department,
        is_teacher=data.get('is_teacher', False),
        created_by=user,
        updated_by=user,
    )
    
    return staff


@transaction.atomic
def update_staff_in_db(staff_id: str, data: dict, position_id: Optional[str] = None,
                       department_id: Optional[str] = None, manager_id: Optional[str] = None, user=None) -> Optional[Staff]:
    """
    Update staff record in database
    
    Args:
        staff_id: Staff ID
        data: Update data dictionary
        position_id: Position ID (optional)
        department_id: Department ID (optional)
        manager_id: Manager ID (optional)
        user: User updating the staff
        
    Returns:
        Updated Staff instance or None if not found
    """
    try:
        staff = Staff.objects.get(id=staff_id)
    except Staff.DoesNotExist:
        return None
    
    # Update position if provided
    if position_id:
        position = Position.objects.filter(id=position_id).first()
        if position:
            staff.position = position
    
    # Update department if provided
    if department_id:
        department = Department.objects.filter(id=department_id).first()
        if department:
            staff.primary_department = department
    
    # Update manager if provided
    if manager_id:
        if str(staff.id) == str(manager_id):
            raise ValueError("A staff member cannot be their own manager.")
        manager = Staff.objects.filter(id=manager_id).first()
        if manager:
            staff.manager = manager
    
    # Update fields
    for field, value in data.items():
        # Skip position, primary_department, and manager since they're handled above
        if field in ['position', 'primary_department', 'manager']:
            continue
        if hasattr(staff, field) and field not in ['id', 'created_at', 'created_by']:
            setattr(staff, field, value)
    
    staff.updated_by = user
    staff.save()
    
    return staff


def delete_staff_from_db(staff_id: str) -> bool:
    """
    Delete staff from database
    
    Args:
        staff_id: Staff ID
        
    Returns:
        True if deleted, False if not found
    """
    try:
        Staff.objects.get(id=staff_id).delete()
        return True
    except Staff.DoesNotExist:
        return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def check_staff_exists_by_id(id_number: str) -> bool:
    """Check if staff exists with given ID number"""
    query = Q(id_number=id_number)
    return Staff.objects.filter(query).exists()


def check_staff_exists_by_email(email: str, exclude_id: Optional[str] = None) -> bool:
    """Check if staff exists with given email"""
    query = Q(email__iexact=email)
    if exclude_id:
        query &= ~Q(id=exclude_id)
    return Staff.objects.filter(query).exists()


def check_staff_exists_by_name_dob(first_name: str, last_name: str, date_of_birth: str,
                                     gender: str, exclude_id: Optional[str] = None) -> bool:
    """Check if staff exists with same name, DOB, and gender"""
    query = Q(
        first_name__iexact=first_name,
        last_name__iexact=last_name,
        date_of_birth=date_of_birth,
        gender=gender
    )
    if exclude_id:
        query &= ~Q(id=exclude_id)
    return Staff.objects.filter(query).exists()


def staff_has_user_account(staff_id: str) -> bool:
    """Check if staff has a linked user account"""
    try:
        staff = Staff.objects.get(id=staff_id)
        return bool(staff.user_account_id_number)
    except Staff.DoesNotExist:
        return False


def staff_has_teaching_sections(staff_id: str) -> bool:
    """Check if staff has teaching sections assigned"""
    try:
        staff = Staff.objects.get(id=staff_id)
        return hasattr(staff, 'teacher_sections') and staff.teacher_sections.exists()
    except Staff.DoesNotExist:
        return False


def get_staff_by_id_or_id_number(identifier: str) -> Optional[Staff]:
    """Get staff by ID or ID number"""
    return Staff.objects.filter(
        Q(id=identifier) | Q(id_number=identifier)
    ).first()

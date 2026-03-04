"""
Position Django Adapter - Database Operations

This module handles all Django-specific database operations for positions.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional
from django.db import transaction

from staff.models import Position, PositionCategory, Department
from business.staff.staff_models import PositionData


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_position_to_data(position) -> PositionData:
    """Convert Django Position model to business data object"""
    return PositionData(
        id=str(position.id),
        title=position.title,
        code=position.code or "",
        description=position.description or None,
        level=position.level,
        employment_type=position.employment_type,
        compensation_type=position.compensation_type,
        salary_min=float(position.salary_min) if position.salary_min else None,
        salary_max=float(position.salary_max) if position.salary_max else None,
        teaching_role=position.teaching_role,
        can_delete=position.can_delete,
        category_id=str(position.category_id) if position.category_id else None,
        department_id=str(position.department_id) if position.department_id else None,
    )


# =============================================================================
# POSITION DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_position_in_db(data: dict, category_id: Optional[str] = None,
                          department_id: Optional[str] = None, user=None) -> Position:
    """Create position in database"""
    
    category = None
    if category_id:
        category = PositionCategory.objects.filter(id=category_id).first()
    
    department = None
    if department_id:
        department = Department.objects.filter(id=department_id).first()
    
    position = Position.objects.create(
        title=data['title'],
        code=data.get('code', ''),
        description=data.get('description'),
        level=data.get('level', 1),
        employment_type=data.get('employment_type', 'full_time'),
        compensation_type=data.get('compensation_type', 'salary'),
        salary_min=data.get('salary_min'),
        salary_max=data.get('salary_max'),
        teaching_role=data.get('teaching_role', False),
        can_delete=data.get('can_delete', True),
        category=category,
        department=department,
        created_by=user,
        updated_by=user,
    )
    
    return position


def update_position_in_db(position_id: str, data: dict, user=None) -> Optional[Position]:
    """Update position in database"""
    try:
        position = Position.objects.get(id=position_id)
        
        for field, value in data.items():
            if hasattr(position, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(position, field, value)
        
        position.updated_by = user
        position.save()
        
        return position
    except Position.DoesNotExist:
        return None


def delete_position_from_db(position_id: str) -> bool:
    """Delete position from database"""
    try:
        Position.objects.get(id=position_id).delete()
        return True
    except Position.DoesNotExist:
        return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def position_has_staff(position_id: str) -> bool:
    """Check if position has staff assigned"""
    try:
        position = Position.objects.get(id=position_id)
        return hasattr(position, 'staff_set') and position.staff_set.exists()
    except Position.DoesNotExist:
        return False

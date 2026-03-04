"""
Division Django Adapter

Django-specific database operations for divisions.
"""

from typing import Optional, List, Dict, Any
from django.db import transaction

from academics.models import Division
from business.core.core_models import DivisionData


def django_division_to_data(division: Division) -> DivisionData:
    """Convert Django Division model to business data object"""
    return DivisionData(
        id=str(division.id),
        name=division.name,
        description=division.description,
        order=getattr(division, 'order', 0),
    )


@transaction.atomic
def create_division_in_db(data: Dict[str, Any], user=None) -> Division:
    """
    Create division in database
    
    Args:
        data: Prepared division data
        user: User creating the division
        
    Returns:
        Created Division instance
    """
    
    division = Division.objects.create(
        name=data['name'],
        description=data.get('description'),
        created_by=user,
        updated_by=user,
    )
    
    return division


@transaction.atomic
def update_division_in_db(division_id: str, data: Dict[str, Any], user=None) -> Optional[Division]:
    """
    Update division in database
    
    Args:
        division_id: Division ID
        data: Update data
        user: User updating the division
        
    Returns:
        Updated Division instance or None if not found
    """
    try:
        division = Division.objects.get(id=division_id)
        
        for field, value in data.items():
            if hasattr(division, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(division, field, value)
        
        division.updated_by = user
        division.save()
        
        return division
    except Division.DoesNotExist:
        return None


def delete_division_from_db(division_id: str) -> bool:
    """
    Delete division from database
    
    Returns:
        True if deleted, False if not found
    """
    try:
        Division.objects.get(id=division_id).delete()
        return True
    except Division.DoesNotExist:
        return False


def get_division_by_id(division_id: str) -> Optional[Division]:
    """Get division by ID"""
    return Division.objects.filter(id=division_id).first()


def check_division_has_grade_levels(division_id: str) -> bool:
    """Check if division has associated grade levels"""
    try:
        division = Division.objects.get(id=division_id)
        return hasattr(division, 'grade_levels') and division.grade_levels.exists()
    except Division.DoesNotExist:
        return False


def list_divisions_for_school() -> List[Division]:
    """
    List all divisions
    
    Args:
        
    Returns:
        List of Division instances
    """
    return list(Division.objects.all().order_by('name'))

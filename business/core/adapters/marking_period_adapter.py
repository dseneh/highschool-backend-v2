"""
Marking Period Django Adapter

Django-specific database operations for marking periods.
"""

from typing import Optional, List, Dict, Any
from django.db import transaction
from django.db.models import Q

from academics.models import MarkingPeriod, Semester
from business.core.core_models import MarkingPeriodData


def django_marking_period_to_data(marking_period: MarkingPeriod) -> MarkingPeriodData:
    """Convert Django MarkingPeriod model to business data object"""
    return MarkingPeriodData(
        id=str(marking_period.id),
        semester_id=str(marking_period.semester_id),
        name=marking_period.name,
        short_name=marking_period.short_name or "",
        description=marking_period.description,
        start_date=marking_period.start_date.isoformat(),
        end_date=marking_period.end_date.isoformat(),
    )


@transaction.atomic
def create_marking_period_in_db(data: Dict[str, Any], semester_id: str, user=None) -> MarkingPeriod:
    """
    Create marking period in database
    
    Args:
        data: Prepared marking period data
        semester_id: Semester ID
        user: User creating the marking period
        
    Returns:
        Created MarkingPeriod instance
    """
    semester = Semester.objects.get(id=semester_id)
    
    marking_period = MarkingPeriod.objects.create(
        semester=semester,
        name=data['name'],
        short_name=data.get('short_name', ''),
        description=data.get('description'),
        start_date=data['start_date'],
        end_date=data['end_date'],
        created_by=user,
        updated_by=user,
    )
    
    return marking_period


@transaction.atomic
def update_marking_period_in_db(marking_period_id: str, data: Dict[str, Any], user=None) -> Optional[MarkingPeriod]:
    """
    Update marking period in database
    
    Args:
        marking_period_id: Marking period ID
        data: Update data
        user: User updating the marking period
        
    Returns:
        Updated MarkingPeriod instance or None if not found
    """
    try:
        marking_period = MarkingPeriod.objects.get(id=marking_period_id)
        
        for field, value in data.items():
            if hasattr(marking_period, field) and field not in ['id', 'semester', 'created_at', 'created_by']:
                setattr(marking_period, field, value)
        
        marking_period.updated_by = user
        marking_period.save()
        
        return marking_period
    except MarkingPeriod.DoesNotExist:
        return None


def delete_marking_period_from_db(marking_period_id: str) -> bool:
    """
    Delete marking period from database
    
    Returns:
        True if deleted, False if not found
    """
    try:
        MarkingPeriod.objects.get(id=marking_period_id).delete()
        return True
    except MarkingPeriod.DoesNotExist:
        return False


def get_marking_period_by_id(marking_period_id: str) -> Optional[MarkingPeriod]:
    """Get marking period by ID"""
    try:
        return MarkingPeriod.objects.get(id=marking_period_id)
    except MarkingPeriod.DoesNotExist:
        return None


def get_semester_by_id(semester_id: str) -> Optional[Semester]:
    """Get semester by ID or name"""
    return Semester.objects.filter(Q(id=semester_id) | Q(name=semester_id)).first()


def list_marking_periods_for_semester(semester_id: str) -> List[MarkingPeriod]:
    """
    List all marking periods for a semester
    
    Args:
        semester_id: Semester ID
        
    Returns:
        List of MarkingPeriod instances
    """
    return list(MarkingPeriod.objects.filter(semester_id=semester_id).order_by('start_date'))


def list_marking_periods_for_school() -> List[MarkingPeriod]:
    """
    List all marking periods
        
    Returns:
        List of MarkingPeriod instances
    """
    return list(MarkingPeriod.objects.all().order_by('start_date'))
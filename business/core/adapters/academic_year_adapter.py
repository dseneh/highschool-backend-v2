"""
Academic Year Django Adapter

Django-specific database operations for academic years.
"""

from typing import Optional, List, Dict, Any
from django.db import transaction

from academics.models import AcademicYear
from business.core.core_models import AcademicYearData


def django_academic_year_to_data(academic_year: AcademicYear) -> AcademicYearData:
    """Convert Django AcademicYear model to business data object"""
    return AcademicYearData(
        id=str(academic_year.id),
        start_date=academic_year.start_date.isoformat(),
        end_date=academic_year.end_date.isoformat(),
        name=academic_year.name or "",
        current=academic_year.current,
        status=academic_year.status,
    )


@transaction.atomic
def create_academic_year_in_db(data: Dict[str, Any], user=None) -> AcademicYear:
    """
    Create academic year in database
    
    Args:
        data: Prepared academic year data (with date objects)
        user: User creating the academic year
        
    Returns:
        Created AcademicYear instance
    """
    
    # If this is set as current, unset existing current year
    if data.get('current', False):
        AcademicYear.objects.filter(current=True).update(current=False)
    
    academic_year = AcademicYear.objects.create(
        start_date=data['start_date'],
        end_date=data['end_date'],
        name=data.get('name', ''),
        current=data.get('current', False),
        status=data.get('status', 'active'),
        created_by=user,
        updated_by=user,
    )
    
    return academic_year


@transaction.atomic
def update_academic_year_in_db(year_id: str, data: Dict[str, Any], user=None) -> Optional[AcademicYear]:
    """
    Update academic year in database
    
    Args:
        year_id: Academic year ID
        data: Update data (with date objects if dates included)
        user: User updating the academic year
        
    Returns:
        Updated AcademicYear instance or None if not found
    """
    try:
        academic_year = AcademicYear.objects.get(id=year_id)
        
        # If setting as current, unset existing current year
        if data.get('current', False) and not academic_year.current:
            AcademicYear.objects.filter(current=True).update(current=False)
        
        # Update fields
        for field, value in data.items():
            if hasattr(academic_year, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(academic_year, field, value)
        
        academic_year.updated_by = user
        academic_year.save()
        
        return academic_year
    except AcademicYear.DoesNotExist:
        return None


def delete_academic_year_from_db(year_id: str) -> bool:
    """
    Delete academic year from database
    
    Returns:
        True if deleted, False if not found
    """
    try:
        AcademicYear.objects.get(id=year_id).delete()
        return True
    except AcademicYear.DoesNotExist:
        return False


def get_academic_year_by_id(year_id: str) -> Optional[AcademicYear]:
    """Get academic year by ID"""
    try:
        return AcademicYear.objects.get(id=year_id)
    except AcademicYear.DoesNotExist:
        return None


def get_existing_academic_years(exclude_id: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Get existing academic years for overlap checking
    
    Returns:
        List of dicts with start_date and end_date as ISO strings
    """
    queryset = AcademicYear.objects.all()
    if exclude_id:
        queryset = queryset.exclude(id=exclude_id)
    
    return [
        {
            'start_date': year.start_date.isoformat(),
            'end_date': year.end_date.isoformat(),
        }
        for year in queryset
    ]


def get_current_academic_year() -> Optional[AcademicYear]:
    """Get the current academic year for the tenant"""
    return AcademicYear.objects.filter(current=True).first()


def check_academic_year_has_enrollments(year_id: str) -> bool:
    """Check if academic year has student enrollments"""
    try:
        year = AcademicYear.objects.get(id=year_id)
        # Check if year has related enrollments (assuming relationship exists)
        return hasattr(year, 'enrollments') and year.enrollments.exists()
    except AcademicYear.DoesNotExist:
        return False


def list_academic_years(active_only: bool = True) -> List[AcademicYear]:
    """
    List all academic years for a tenant
    
    Args:
        active_only: If True, only return active years
        
    Returns:
        List of AcademicYear instances
    """
    queryset = AcademicYear.objects.all()
    if active_only:
        queryset = queryset.filter(active=True)
    return list(queryset.order_by('-start_date'))

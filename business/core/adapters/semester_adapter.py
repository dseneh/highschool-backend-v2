"""
Semester Django Adapter

Django-specific database operations for semesters.
"""

from typing import Optional, List, Dict, Any
from django.db import transaction

from academics.models import AcademicYear, Semester
from business.core.core_models import SemesterData


def django_semester_to_data(semester: Semester) -> SemesterData:
    """Convert Django Semester model to business data object"""
    return SemesterData(
        id=str(semester.id),
        academic_year_id=str(semester.academic_year_id) if semester.academic_year_id else None,
        name=semester.name,
        start_date=semester.start_date.isoformat() if semester.start_date else None,
        end_date=semester.end_date.isoformat() if semester.end_date else None,
    )


@transaction.atomic
def create_semester_in_db(data: Dict[str, Any], 
                         academic_year_id: Optional[str] = None, 
                         user=None) -> Semester:
    """
    Create semester in database
    
    Args:
        data: Prepared semester data
        academic_year_id: Optional academic year ID
        user: User creating the semester
        
    Returns:
        Created Semester instance
    """
    
    academic_year = None
    if academic_year_id:
        academic_year = AcademicYear.objects.filter(id=academic_year_id).first()
    else:
        academic_year = AcademicYear.get_current_academic_year()
    
    semester = Semester.objects.create(
        academic_year=academic_year,
        name=data['name'],
        start_date=data.get('start_date'),
        end_date=data.get('end_date'),
        created_by=user,
        updated_by=user,
    )
    
    return semester


@transaction.atomic
def update_semester_in_db(semester_id: str, data: Dict[str, Any], user=None) -> Optional[Semester]:
    """
    Update semester in database
    
    Args:
        semester_id: Semester ID
        data: Update data
        user: User updating the semester
        
    Returns:
        Updated Semester instance or None if not found
    """
    try:
        semester = Semester.objects.get(id=semester_id)
        
        for field, value in data.items():
            if hasattr(semester, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(semester, field, value)
        
        semester.updated_by = user
        semester.save()
        
        return semester
    except Semester.DoesNotExist:
        return None


def delete_semester_from_db(semester_id: str) -> bool:
    """
    Delete semester from database
    
    Returns:
        True if deleted, False if not found
    """
    try:
        Semester.objects.get(id=semester_id).delete()
        return True
    except Semester.DoesNotExist:
        return False


def get_semester_by_id(semester_id: str) -> Optional[Semester]:
    """Get semester by ID"""
    try:
        from django.db.models import Q
        return Semester.objects.filter(Q(id=semester_id) | Q(name=semester_id)).first()
    except Semester.DoesNotExist:
        return None


def list_semesters_for_school() -> List[Semester]:
    """
    List all semesters
    
    Returns:
        List of Semester instances
    """
    return list(Semester.objects.all().order_by('-start_date'))

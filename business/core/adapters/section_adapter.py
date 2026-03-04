"""
Section Django Adapter

Django-specific database operations for sections.
"""

from typing import Optional, List, Dict, Any
from django.db import transaction

from academics.models import Section, GradeLevel
from business.core.core_models import SectionData


def django_section_to_data(section: Section) -> SectionData:
    """Convert Django Section model to business data object"""
    return SectionData(
        id=str(section.id),
        name=section.name,
        max_capacity=section.max_capacity,
        room_number=section.room_number,
        description=section.description,
    )


@transaction.atomic
def create_section_in_db(data: Dict[str, Any], 
                        grade_level_id: Optional[str] = None, 
                        user=None) -> Section:
    """
    Create section in database
    
    Args:
        data: Prepared section data
        grade_level_id: Optional grade level ID
        user: User creating the section
        
    Returns:
        Created Section instance
    """    

    grade_level = None
    if grade_level_id:
        grade_level = GradeLevel.objects.filter(id=grade_level_id).first()
    
    section = Section.objects.create(
        name=data['name'],
        grade_level=grade_level,
        max_capacity=data.get('max_capacity'),
        room_number=data.get('room_number'),
        description=data.get('description'),
        created_by=user,
        updated_by=user,
    )
    
    return section


@transaction.atomic
def update_section_in_db(section_id: str, data: Dict[str, Any], user=None) -> Optional[Section]:
    """
    Update section in database
    
    Args:
        section_id: Section ID
        data: Update data
        user: User updating the section
        
    Returns:
        Updated Section instance or None if not found
    """
    try:
        section = Section.objects.get(id=section_id)
        
        for field, value in data.items():
            if hasattr(section, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(section, field, value)
        
        section.updated_by = user
        section.save()
        
        return section
    except Section.DoesNotExist:
        return None


def delete_section_from_db(section_id: str) -> bool:
    """
    Delete section from database
    
    Returns:
        True if deleted, False if not found
    """
    try:
        Section.objects.get(id=section_id).delete()
        return True
    except Section.DoesNotExist:
        return False


@transaction.atomic
def deactivate_section_in_db(section_id: str) -> Optional[Section]:
    """
    Deactivate section instead of deleting
    
    Returns:
        Updated Section instance or None if not found
    """
    try:
        section = Section.objects.get(id=section_id)
        section.active = False
        section.save()
        return section
    except Section.DoesNotExist:
        return None


def get_section_by_id(section_id: str) -> Optional[Section]:
    """Get section by ID"""
    try:
        return Section.objects.get(id=section_id)
    except Section.DoesNotExist:
        return None


def check_section_has_enrollments(section_id: str) -> bool:
    """Check if section has enrolled students"""
    try:
        section = Section.objects.get(id=section_id)
        return hasattr(section, 'enrollments') and section.enrollments.exists()
    except Section.DoesNotExist:
        return False


def list_sections_for_grade_level(grade_level_id: str) -> List[Section]:
    """
    List all sections for a grade level
    
    Args:
        grade_level_id: Grade level ID
        
    Returns:
        List of Section instances
    """
    return list(Section.objects.filter(grade_level_id=grade_level_id).select_related('grade_level').order_by('name'))


def list_sections_for_school() -> List[Section]:
    """
    List all sections
        
    Returns:
        List of Section instances
    """
    return list(Section.objects.all().order_by('name'))

"""
Grade Level Django Adapter

Django-specific database operations for grade levels.
"""

from typing import Optional, List, Dict, Any
from django.db import transaction

from academics.models import GradeLevel
from business.core.core_models import GradeLevelData


def django_grade_level_to_data(grade_level: GradeLevel) -> GradeLevelData:
    """Convert Django GradeLevel model to business data object"""
    return GradeLevelData(
        id=str(grade_level.id),
        name=grade_level.name,
        level=grade_level.level,
        short_name=grade_level.short_name,
        description=grade_level.description,
        order=getattr(grade_level, 'order', 0),
    )


@transaction.atomic
def create_grade_level_in_db(data: Dict[str, Any], user=None) -> GradeLevel:
    """
    Create grade level in database
    
    Args:
        data: Prepared grade level data
        user: User creating the grade level
        
    Returns:
        Created GradeLevel instance
    """
    
    grade_level = GradeLevel.objects.create(
        name=data['name'],
        level=data.get('level', 1),
        short_name=data.get('short_name'),
        description=data.get('description'),
        created_by=user,
        updated_by=user,
    )
    
    return grade_level


@transaction.atomic
def update_grade_level_in_db(grade_level_id: str, data: Dict[str, Any], user=None) -> Optional[GradeLevel]:
    """
    Update grade level in database
    
    Args:
        grade_level_id: Grade level ID
        data: Update data
        user: User updating the grade level
        
    Returns:
        Updated GradeLevel instance or None if not found
    """
    try:
        grade_level = GradeLevel.objects.get(id=grade_level_id)
        
        for field, value in data.items():
            if hasattr(grade_level, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(grade_level, field, value)
        
        grade_level.updated_by = user
        grade_level.save()
        
        return grade_level
    except GradeLevel.DoesNotExist:
        return None


def delete_grade_level_from_db(grade_level_id: str) -> bool:
    """
    Delete grade level from database
    
    Returns:
        True if deleted, False if not found
    """
    try:
        GradeLevel.objects.get(id=grade_level_id).delete()
        return True
    except GradeLevel.DoesNotExist:
        return False


def get_grade_level_by_id(grade_level_id: str) -> Optional[GradeLevel]:
    """Get grade level by ID"""
    try:
        return GradeLevel.objects.get(id=grade_level_id)
    except GradeLevel.DoesNotExist:
        return None


def check_grade_level_has_students(grade_level_id: str) -> bool:
    """Check if grade level has students assigned"""
    try:
        grade_level = GradeLevel.objects.get(id=grade_level_id)
        return hasattr(grade_level, 'enrollments') and grade_level.enrollments.exists()
    except GradeLevel.DoesNotExist:
        return False


def check_grade_level_has_sections(grade_level_id: str) -> bool:
    """Check if grade level has sections"""
    try:
        grade_level = GradeLevel.objects.get(id=grade_level_id)
        return hasattr(grade_level, 'sections') and grade_level.sections.exists()
    except GradeLevel.DoesNotExist:
        return False


def list_grade_levels_for_school(active_only: bool = True) -> List[GradeLevel]:
    """
    List all grade levels
    
    Args:
        active_only: If True, only return active grade levels
        
    Returns:
        List of GradeLevel instances ordered by level
    """
    queryset = GradeLevel.objects.all()
    if active_only:
        queryset = queryset.filter(active=True)
    return list(queryset.order_by('level'))


def get_next_grade_level_number() -> int:
    """
    Get the next available grade level number
        
    Returns:
        Next level number (1 if no levels exist)
    """
    last_level = GradeLevel.objects.order_by('-level').first()
    return int(last_level.level) + 1 if last_level else 1

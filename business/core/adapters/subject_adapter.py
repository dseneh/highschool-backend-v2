"""
Subject Django Adapter

Django-specific database operations for subjects.
"""

from typing import Optional, List, Dict, Any
from django.db import transaction

from academics.models import Subject
from business.core.core_models import SubjectData


def django_subject_to_data(subject: Subject) -> SubjectData:
    """Convert Django Subject model to business data object"""
    return SubjectData(
        id=str(subject.id),
        name=subject.name,
        code=subject.code or "",
        description=subject.description,
        credits=float(subject.credits) if subject.credits else None,
        category=getattr(subject, 'category', None),
    )


@transaction.atomic
def create_subject_in_db(data: Dict[str, Any], user=None) -> Subject:
    """
    Create subject in database
    
    Args:
        data: Prepared subject data
        user: User creating the subject
        
    Returns:
        Created Subject instance
    """
    
    subject = Subject.objects.create(
        name=data['name'],
        code=data.get('code', ''),
        description=data.get('description'),
        credits=data.get('credits'),
        created_by=user,
        updated_by=user,
    )
    
    return subject


@transaction.atomic
def update_subject_in_db(subject_id: str, data: Dict[str, Any], user=None) -> Optional[Subject]:
    """
    Update subject in database
    
    Args:
        subject_id: Subject ID
        data: Update data
        user: User updating the subject
        
    Returns:
        Updated Subject instance or None if not found
    """
    try:
        subject = Subject.objects.get(id=subject_id)
        
        for field, value in data.items():
            if hasattr(subject, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(subject, field, value)
        
        subject.updated_by = user
        subject.save()
        
        return subject
    except Subject.DoesNotExist:
        return None


def delete_subject_from_db(subject_id: str) -> bool:
    """
    Delete subject from database
    
    Returns:
        True if deleted, False if not found
    """
    try:
        Subject.objects.get(id=subject_id).delete()
        return True
    except Subject.DoesNotExist:
        return False


@transaction.atomic
def deactivate_subject_in_db(subject_id: str) -> Optional[Subject]:
    """
    Deactivate subject instead of deleting
    
    Returns:
        Updated Subject instance or None if not found
    """
    try:
        subject = Subject.objects.get(id=subject_id)
        subject.active = False
        subject.save()
        return subject
    except Subject.DoesNotExist:
        return None


def get_subject_by_id(subject_id: str) -> Optional[Subject]:
    """Get subject by ID"""
    try:
        return Subject.objects.get(id=subject_id)
    except Subject.DoesNotExist:
        return None


def check_subject_has_gradebooks(subject_id: str) -> bool:
    """Check if subject has gradebooks"""
    try:
        subject = Subject.objects.get(id=subject_id)
        return hasattr(subject, 'grade_books') and subject.grade_books.exists()
    except Subject.DoesNotExist:
        return False


def check_subject_has_grades(subject_id: str) -> bool:
    """Check if subject has grades assigned"""
    try:
        subject = Subject.objects.get(id=subject_id)
        if hasattr(subject, 'grade_books'):
            return subject.grade_books.filter(grade__isnull=False).exists()
        return False
    except Subject.DoesNotExist:
        return False


def list_subjects_for_tenant(active_only: bool = False) -> List[Subject]:
    """
    List all subjects
    
    Args:
        active_only: If True, only return active subjects
        
    Returns:
        List of Subject instances
    """
    queryset = Subject.objects.all()
    if active_only:
        queryset = queryset.filter(active=True)
    return list(queryset.order_by('name'))

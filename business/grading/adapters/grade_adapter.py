"""
Grade Django Adapter - Database Operations

This module handles all Django-specific database operations for grades.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional, List, Dict
from django.db import transaction
from django.db.models import Q, Avg, Count, Min, Max
from decimal import Decimal

from grading.models import Grade, Assessment, GradeBook, GradeLetter, AssessmentType
from students.models import Enrollment
from academics.models import MarkingPeriod
from business.grading.grading_models import (
    GradeData, AssessmentData, GradeLetterData
)


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_grade_to_data(grade) -> GradeData:
    """Convert Django Grade model to business data object"""
    return GradeData(
        id=str(grade.id),
        assessment_id=str(grade.assessment_id),
        student_id=str(grade.student_id),
        enrollment_id=str(grade.enrollment_id) if grade.enrollment_id else "",
        score=Decimal(str(grade.score)) if grade.score is not None else None,
        status=grade.status,
        comments=grade.comments or "",
    )


def django_assessment_to_data(assessment) -> AssessmentData:
    """Convert Django Assessment model to business data object"""
    return AssessmentData(
        id=str(assessment.id),
        gradebook_id=str(assessment.gradebook_id),
        assessment_type_id=str(assessment.assessment_type_id),
        marking_period_id=str(assessment.marking_period_id),
        name=assessment.name,
        max_score=Decimal(str(assessment.max_score)),
        weight=Decimal(str(assessment.weight)),
        due_date=assessment.due_date.isoformat() if assessment.due_date else None,
        active=assessment.active,
    )


def django_grade_letter_to_data(letter) -> GradeLetterData:
    """Convert Django GradeLetter model to business data object"""
    return GradeLetterData(
        id=str(letter.id),
        letter=letter.letter,
        min_percentage=Decimal(str(letter.min_percentage)),
        max_percentage=Decimal(str(letter.max_percentage)),
        order=letter.order,
    )


# =============================================================================
# LOOKUP FUNCTIONS
# =============================================================================

def get_assessment_by_id(assessment_id: str) -> Optional[Assessment]:
    """Get assessment by ID"""
    try:
        return Assessment.objects.select_related(
            'gradebook', 'assessment_type', 'marking_period'
        ).get(id=assessment_id)
    except Assessment.DoesNotExist:
        return None


def get_grade_by_id(grade_id: str) -> Optional[Grade]:
    """Get grade by ID"""
    try:
        return Grade.objects.select_related(
            'assessment', 'student', 'enrollment'
        ).get(id=grade_id)
    except Grade.DoesNotExist:
        return None


def get_gradebook_by_id(gradebook_id: str) -> Optional[GradeBook]:
    """Get gradebook by ID"""
    try:
        return GradeBook.objects.select_related(
            'academic_year', 'section_subject',
            'section_subject__section', 'section_subject__subject'
        ).get(id=gradebook_id)
    except GradeBook.DoesNotExist:
        return None


def get_enrollment_by_id(enrollment_id: str) -> Optional[Enrollment]:
    """Get enrollment by ID"""
    try:
        return Enrollment.objects.select_related('student', 'academic_year').get(id=enrollment_id)
    except Enrollment.DoesNotExist:
        return None


def get_marking_period_by_id(period_id: str) -> Optional[MarkingPeriod]:
    """Get marking period by ID"""
    try:
        return MarkingPeriod.objects.get(id=period_id)
    except MarkingPeriod.DoesNotExist:
        return None


def get_assessment_type_by_id(type_id: str) -> Optional[AssessmentType]:
    """Get assessment type by ID"""
    try:
        return AssessmentType.objects.get(id=type_id)
    except AssessmentType.DoesNotExist:
        return None


# =============================================================================
# GRADE DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_grade_in_db(data: dict, assessment_id: str, enrollment_id: str,
                      student_id: str, user=None) -> Optional[Grade]:
    """
    Create grade in database
    
    Args:
        data: Prepared grade data
        assessment_id: Assessment ID
        enrollment_id: Enrollment ID
        student_id: Student ID
        user: User creating the grade
        
    Returns:
        Created Grade instance or None if failed
    """
    try:
        assessment = Assessment.objects.get(id=assessment_id)
        enrollment = Enrollment.objects.get(id=enrollment_id)
        
        grade = Grade.objects.create(
            assessment=assessment,
            enrollment=enrollment,
            student_id=student_id,
            score=data.get('score'),
            status=data.get('status', 'draft'),
            comments=data.get('comments', ''),
            created_by=user,
            updated_by=user,
        )
        
        return grade
    except Exception:
        return None


@transaction.atomic
def update_grade_in_db(grade_id: str, data: dict, user=None) -> Optional[Grade]:
    """
    Update grade in database
    
    Args:
        grade_id: Grade ID
        data: Update data dictionary
        user: User updating the grade
        
    Returns:
        Updated Grade instance or None if not found
    """
    try:
        grade = Grade.objects.get(id=grade_id)
        
        # Update fields
        for field, value in data.items():
            if hasattr(grade, field) and field not in ['id', 'assessment', 'enrollment', 'student', 'created_at', 'created_by']:
                setattr(grade, field, value)
        
        grade.updated_by = user
        grade.save()
        
        return grade
    except Grade.DoesNotExist:
        return None


def delete_grade_from_db(grade_id: str) -> bool:
    """Delete grade from database"""
    try:
        Grade.objects.get(id=grade_id).delete()
        return True
    except Grade.DoesNotExist:
        return False


def get_grades_by_assessment(assessment_id: str) -> List[Grade]:
    """Get all grades for an assessment"""
    return list(
        Grade.objects.filter(assessment_id=assessment_id)
        .select_related('student', 'enrollment')
        .order_by('student__last_name', 'student__first_name')
    )


def get_grades_by_student(student_id: str, marking_period_id: Optional[str] = None) -> List[Grade]:
    """Get all grades for a student"""
    qs = Grade.objects.filter(student_id=student_id).select_related(
        'assessment', 'assessment__assessment_type', 'assessment__marking_period'
    )
    
    if marking_period_id:
        qs = qs.filter(assessment__marking_period_id=marking_period_id)
    
    return list(qs.order_by('-assessment__due_date'))


def get_grade_by_assessment_and_enrollment(assessment_id: str, 
                                          enrollment_id: str) -> Optional[Grade]:
    """Get grade for specific assessment and enrollment"""
    return Grade.objects.filter(
        assessment_id=assessment_id,
        enrollment_id=enrollment_id
    ).first()


@transaction.atomic
def bulk_create_grades_in_db(grades_data: List[dict], user=None) -> List[Grade]:
    """
    Create multiple grades in database
    
    Args:
        grades_data: List of grade data dictionaries
        user: User creating the grades
        
    Returns:
        List of created Grade instances
    """
    grades = []
    
    for data in grades_data:
        grade = create_grade_in_db(
            data=data,
            assessment_id=data['assessment_id'],
            enrollment_id=data['enrollment_id'],
            student_id=data['student_id'],
            user=user
        )
        if grade:
            grades.append(grade)
    
    return grades


# =============================================================================
# ASSESSMENT DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_assessment_in_db(data: dict, gradebook_id: str, assessment_type_id: str,
                           marking_period_id: str, user=None) -> Optional[Assessment]:
    """
    Create assessment in database
    
    Args:
        data: Prepared assessment data
        gradebook_id: Gradebook ID
        assessment_type_id: Assessment type ID
        marking_period_id: Marking period ID
        user: User creating the assessment
        
    Returns:
        Created Assessment instance or None if failed
    """
    try:
        gradebook = GradeBook.objects.get(id=gradebook_id)
        assessment_type = AssessmentType.objects.get(id=assessment_type_id)
        marking_period = MarkingPeriod.objects.get(id=marking_period_id)
        
        assessment = Assessment.objects.create(
            gradebook=gradebook,
            assessment_type=assessment_type,
            marking_period=marking_period,
            name=data['name'],
            max_score=data['max_score'],
            weight=data['weight'],
            due_date=data.get('due_date'),
            active=data.get('active', True),
            created_by=user,
            updated_by=user,
        )
        
        return assessment
    except Exception:
        return None


@transaction.atomic
def update_assessment_in_db(assessment_id: str, data: dict, user=None) -> Optional[Assessment]:
    """Update assessment in database"""
    try:
        assessment = Assessment.objects.get(id=assessment_id)
        
        for field, value in data.items():
            if hasattr(assessment, field) and field not in ['id', 'gradebook', 'created_at', 'created_by']:
                setattr(assessment, field, value)
        
        assessment.updated_by = user
        assessment.save()
        
        return assessment
    except Assessment.DoesNotExist:
        return None


def delete_assessment_from_db(assessment_id: str) -> bool:
    """Delete assessment from database"""
    try:
        Assessment.objects.get(id=assessment_id).delete()
        return True
    except Assessment.DoesNotExist:
        return False


def get_assessments_by_gradebook(gradebook_id: str, 
                                 marking_period_id: Optional[str] = None) -> List[Assessment]:
    """Get all assessments for a gradebook"""
    qs = Assessment.objects.filter(gradebook_id=gradebook_id).select_related(
        'assessment_type', 'marking_period'
    )
    
    if marking_period_id:
        qs = qs.filter(marking_period_id=marking_period_id)
    
    return list(qs.order_by('due_date', 'name'))


def check_assessment_name_exists(name: str, gradebook_id: str, marking_period_id: str,
                                 exclude_id: Optional[str] = None) -> bool:
    """Check if assessment name already exists in gradebook"""
    query = Q(name__iexact=name, gradebook_id=gradebook_id, marking_period_id=marking_period_id)
    if exclude_id:
        query &= ~Q(id=exclude_id)
    return Assessment.objects.filter(query).exists()


# =============================================================================
# GRADE LETTER DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_grade_letter_in_db(data: dict, user=None) -> Optional[GradeLetter]:
    """Create grade letter in database"""    
    try:
        
        letter = GradeLetter.objects.create(
            letter=data['letter'],
            min_percentage=data['min_percentage'],
            max_percentage=data['max_percentage'],
            order=data.get('order', 0),
            created_by=user,
            updated_by=user,
        )
        
        return letter
    except Exception:
        return None


@transaction.atomic
def update_grade_letter_in_db(letter_id: str, data: dict, user=None) -> Optional[GradeLetter]:
    """Update grade letter in database"""
    try:
        letter = GradeLetter.objects.get(id=letter_id)
        
        for field, value in data.items():
            if hasattr(letter, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(letter, field, value)
        
        letter.updated_by = user
        letter.save()
        
        return letter
    except GradeLetter.DoesNotExist:
        return None


def delete_grade_letter_from_db(letter_id: str) -> bool:
    """Delete grade letter from database"""
    try:
        GradeLetter.objects.get(id=letter_id).delete()
        return True
    except GradeLetter.DoesNotExist:
        return False


def get_grade_letters_by_school() -> List[Dict]:
    """Get all grade letters (as dictionaries for business logic)"""
    letters = GradeLetter.objects.all().order_by('order', '-max_percentage')
    
    return [
        {
            'id': str(letter.id),
            'letter': letter.letter,
            'min_percentage': letter.min_percentage,
            'max_percentage': letter.max_percentage,
            'order': letter.order,
        }
        for letter in letters
    ]


# =============================================================================
# STATISTICS AND AGGREGATION
# =============================================================================

def get_assessment_statistics(assessment_id: str) -> Dict:
    """Get statistics for an assessment"""
    stats = Grade.objects.filter(
        assessment_id=assessment_id,
        score__isnull=False
    ).aggregate(
        count=Count('id'),
        average=Avg('score'),
        min_score=Min('score'),
        max_score=Max('score')
    )
    
    return {
        'count': stats['count'] or 0,
        'average': float(stats['average']) if stats['average'] else None,
        'min': float(stats['min_score']) if stats['min_score'] else None,
        'max': float(stats['max_score']) if stats['max_score'] else None,
    }


def get_student_grade_summary(student_id: str, marking_period_id: str) -> List[Dict]:
    """Get summary of student's grades for a marking period"""
    grades = Grade.objects.filter(
        student_id=student_id,
        assessment__marking_period_id=marking_period_id
    ).select_related(
        'assessment', 'assessment__assessment_type'
    ).values(
        'id', 'score', 'assessment__name', 'assessment__max_score',
        'assessment__weight', 'status'
    )
    
    return [
        {
            'id': str(grade['id']),
            'score': float(grade['score']) if grade['score'] else None,
            'max_score': float(grade['assessment__max_score']),
            'weight': float(grade['assessment__weight']),
            'status': grade['status'],
        }
        for grade in grades
    ]

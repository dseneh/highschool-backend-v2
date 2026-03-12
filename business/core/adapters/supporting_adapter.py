"""
Additional Core Adapters - Database Operations for Supporting Entities

This module handles Django-specific database operations for Period, PeriodTime, 
SectionSchedule, SectionSubject, and GradeLevelTuitionFee.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional, List, Dict, Any
from django.db import transaction
from django.db.models import Q
import logging

from academics.models import (
    AcademicYear, GradeLevel, GradeLevelTuitionFee, Period, PeriodTime,
    Section, SectionSchedule, SectionSubject, Subject
)
from grading.utils import create_gradebook_with_assessments

logger = logging.getLogger(__name__)


# =============================================================================
# GRADE LEVEL TUITION FEE OPERATIONS
# =============================================================================

def get_grade_level_by_id(grade_level_id: str) -> Optional[GradeLevel]:
    """Get grade level by ID"""
    try:
        return GradeLevel.objects.get(id=grade_level_id)
    except GradeLevel.DoesNotExist:
        return None


def get_tuition_fee_by_id(fee_id: str, grade_level_id: str) -> Optional[GradeLevelTuitionFee]:
    """Get tuition fee by ID for specific grade level"""
    try:
        return GradeLevelTuitionFee.objects.get(id=fee_id, grade_level_id=grade_level_id)
    except GradeLevelTuitionFee.DoesNotExist:
        return None


@transaction.atomic
def bulk_update_tuition_fees(grade_level: GradeLevel, fee_updates: List[Dict[str, Any]], 
                             user=None) -> List[GradeLevelTuitionFee]:
    """
    Bulk update tuition fees
    
    Args:
        grade_level: GradeLevel instance
        fee_updates: List of fee update data
        user: User performing the update
        
    Returns:
        List of updated GradeLevelTuitionFee instances
    """
    from common.cache_service import DataCache
    
    updated_fees = []
    
    for fee_data in fee_updates:
        fee_id = fee_data.get("id")
        amount = fee_data.get("amount")
        
        try:
            tuition_fee = GradeLevelTuitionFee.objects.get(id=fee_id, grade_level=grade_level)
            tuition_fee.amount = amount
            tuition_fee.updated_by = user
            tuition_fee.save()
            updated_fees.append(tuition_fee)
        except GradeLevelTuitionFee.DoesNotExist:
            continue
    
    # Invalidate grade levels cache after updating tuition fees
    if updated_fees:
        DataCache.invalidate_grade_levels()
    
    return updated_fees


# =============================================================================
# PERIOD OPERATIONS
# =============================================================================

def get_period_by_id_or_name(identifier: str) -> Optional[Period]:
    """Get period by ID or name"""
    try:
        f = Q(id=identifier) | Q(name__iexact=identifier)
        return Period.objects.filter(f).first()
    except Period.DoesNotExist:
        return None


def get_school_periods() -> List[Period]:
    """Get all periods for a tenant"""
    return list(Period.objects.all())


def get_period_names_for_school() -> List[str]:
    """Get all period names"""
    return list(Period.objects.values_list('name', flat=True))


def check_period_exists_by_name(name: str) -> bool:
    """Check if period exists with given name"""
    return Period.objects.filter(name__iexact=name).exists()


@transaction.atomic
def create_period_in_db(data: Dict[str, Any], user=None) -> Period:
    """Create period in database"""
    return Period.objects.create(
        name=data['name'],
        description=data.get('description'),
        created_by=user,
        updated_by=user,
    )


def update_period_in_db(period: Period, data: Dict[str, Any], user=None) -> Period:
    """Update period in database"""
    for field, value in data.items():
        if hasattr(period, field) and field not in ['id', 'created_at', 'created_by']:
            setattr(period, field, value)
    
    period.updated_by = user
    period.save()
    return period


def delete_period_from_db(period: Period) -> bool:
    """Delete period from database"""
    try:
        period.delete()
        return True
    except Exception:
        return False


# =============================================================================
# PERIOD TIME OPERATIONS
# =============================================================================

def get_period_time_by_id(period_time_id: str) -> Optional[PeriodTime]:
    """Get period time by ID"""
    try:
        return PeriodTime.objects.filter(id=period_time_id).first()
    except PeriodTime.DoesNotExist:
        return None


def get_period_times_for_period(period: Period) -> List[PeriodTime]:
    """Get all period times for a period"""
    return list(period.period_times.all().order_by("day_of_week", "start_time"))


@transaction.atomic
def create_period_time_in_db(period: Period, data: Dict[str, Any], user=None) -> PeriodTime:
    """Create period time in database"""
    return period.period_times.create(
        start_time=data['start_time'],
        end_time=data['end_time'],
        day_of_week=data['day_of_week'],
        created_by=user,
        updated_by=user,
    )


def update_period_time_in_db(period_time: PeriodTime, data: Dict[str, Any], user=None) -> PeriodTime:
    """Update period time in database"""
    for field, value in data.items():
        if hasattr(period_time, field) and field not in ['id', 'period', 'created_at', 'created_by']:
            setattr(period_time, field, value)
    
    period_time.updated_by = user
    period_time.save()
    return period_time


def delete_period_time_from_db(period_time: PeriodTime) -> bool:
    """Delete period time from database"""
    try:
        period_time.delete()
        return True
    except Exception:
        return False


# =============================================================================
# SECTION SCHEDULE OPERATIONS
# =============================================================================

def get_section_schedule_by_id(schedule_id: str) -> Optional[SectionSchedule]:
    """Get section schedule by ID"""
    try:
        return SectionSchedule.objects.filter(id=schedule_id).first()
    except SectionSchedule.DoesNotExist:
        return None


def get_section_by_id(section_id: str) -> Optional[Section]:
    """Get section by ID"""
    try:
        return Section.objects.filter(id=section_id).first()
    except Section.DoesNotExist:
        return None


def get_subject_by_id(subject_id: str) -> Optional[Subject]:
    """Get subject by ID"""
    try:
        return Subject.objects.filter(id=subject_id).first()
    except Subject.DoesNotExist:
        return None


def get_section_schedules(section: Section) -> List[SectionSchedule]:
    """Get all schedules for a section"""
    return list(section.class_schedules.all())


def check_section_schedule_exists(section: Section, subject_id: str, 
                                  period_id: str, period_time_id: str) -> bool:
    """Check if section schedule already exists"""
    return section.class_schedules.filter(
        subject_id=subject_id,
        period_id=period_id,
        period_time_id=period_time_id
    ).exists()


@transaction.atomic
def create_section_schedule_in_db(section: Section, subject: Subject, period: Period,
                                  period_time: PeriodTime, user=None) -> SectionSchedule:
    """Create section schedule in database"""
    return SectionSchedule.objects.create(
        section=section,
        subject=subject,
        period=period,
        period_time=period_time,
        created_by=user,
        updated_by=user,
    )


def update_section_schedule_in_db(schedule: SectionSchedule, data: Dict[str, Any], 
                                  user=None) -> SectionSchedule:
    """Update section schedule in database"""
    for field, value in data.items():
        if hasattr(schedule, field) and field not in ['id', 'section', 'created_at', 'created_by']:
            setattr(schedule, field, value)
    
    schedule.updated_by = user
    schedule.save()
    return schedule


def delete_section_schedule_from_db(schedule: SectionSchedule) -> bool:
    """Delete section schedule from database"""
    try:
        schedule.delete()
        return True
    except Exception:
        return False


# =============================================================================
# SECTION SUBJECT OPERATIONS
# =============================================================================

def get_section_subject_by_id(section_subject_id: str) -> Optional[SectionSubject]:
    """Get section subject by ID"""
    try:
        return SectionSubject.objects.get(id=section_subject_id)
    except SectionSubject.DoesNotExist:
        return None


def get_section_by_id_or_name(identifier: str) -> Optional[Section]:
    """Get section by ID or name"""
    try:
        f = Q(id=identifier) | Q(name=identifier)
        return Section.objects.get(f)
    except Section.DoesNotExist:
        return None


def get_subject_by_id_or_name(identifier: str) -> Optional[Subject]:
    """Get subject by ID or name"""
    try:
        f = Q(id=identifier) | Q(name__iexact=identifier)
        return Subject.objects.filter(f).first()
    except Subject.DoesNotExist:
        return None


def get_section_subjects(section: Section) -> List[SectionSubject]:
    """Get all subjects for a section"""
    return list(section.section_subjects.all())


def get_assigned_subject_ids(section: Section) -> List[str]:
    """Get list of already assigned subject IDs for a section"""
    return list(section.section_subjects.values_list('subject_id', flat=True))


@transaction.atomic
def bulk_create_section_subjects(section: Section, subject_ids: List[str], 
                                 user=None) -> List[SectionSubject]:
    """
    Bulk create section subjects and their gradebooks atomically.
    
    If gradebook creation fails, the entire operation (including SectionSubject creation)
    will be rolled back, ensuring data consistency.
    
    Args:
        section: Section instance
        subject_ids: List of subject IDs to assign
        user: User performing the assignment
        
    Returns:
        List of created SectionSubject instances
    """
    created_subjects = []
    
    # Get current academic year once (outside loop for efficiency)
    current_academic_year = AcademicYear.objects.filter(current=True).first()
    if not current_academic_year:
        logger.warning(
            f"No current academic year found. SectionSubjects will be created "
            f"but gradebooks will NOT be created for section {section.name}"
        )
    
    for subject_id in subject_ids:
        subject = get_subject_by_id_or_name(subject_id)
        if not subject:
            continue
        
        section_subject, created = section.section_subjects.get_or_create(
            section=section,
            subject=subject,
            defaults={
                'created_by': user,
                'updated_by': user,
            }
        )
        
        if created:
            created_subjects.append(section_subject)
            
            # Create gradebook with assessments immediately after SectionSubject creation
            # This happens in the same transaction, so if it fails, SectionSubject is rolled back
            if current_academic_year:
                try:
                    result = create_gradebook_with_assessments(
                        section_subject=section_subject,
                        academic_year=current_academic_year,
                        name=f"{subject.name} - {section.name}",
                        calculation_method="weighted",
                        created_by=user,
                        auto_generate=True
                    )
                    
                    logger.info(
                        f"Gradebook created for {section.name} - {subject.name}. "
                        f"Assessments generated: {result.get('assessments_generated', False)}"
                    )
                except Exception as e:
                    # Log the error and re-raise to trigger transaction rollback
                    logger.error(
                        f"Failed to create gradebook for {section.name} - {subject.name}: {e}",
                        exc_info=True
                    )
                    raise  # Re-raise to rollback the entire transaction
    
    return created_subjects


def update_section_subject_in_db(section_subject: SectionSubject, data: Dict[str, Any],
                                 user=None) -> SectionSubject:
    """Update section subject in database"""
    for field, value in data.items():
        if hasattr(section_subject, field) and field not in ['id', 'section', 'subject', 'created_at', 'created_by']:
            setattr(section_subject, field, value)
    
    section_subject.updated_by = user
    section_subject.save()
    return section_subject


def section_subject_has_enrollments(section_subject: SectionSubject) -> bool:
    """Check if section subject has enrollments"""
    return section_subject.section.enrollments.exists()


def section_subject_has_grades(section_subject: SectionSubject) -> bool:
    """
    Check if section subject has any grades entered.
    Returns True if any student has a grade for this section-subject combination.
    """
    from grading.models import Grade
    
    # Check if there are any grades for this section-subject's gradebook
    # Using exists() for optimal performance (stops at first match)
    return Grade.objects.filter(
        assessment__gradebook__section_subject=section_subject,
        score__isnull=False  # Only count actual grades, not empty entries
    ).exists()


def deactivate_section_subject(section_subject: SectionSubject) -> SectionSubject:
    """Deactivate section subject instead of deleting"""
    section_subject.active = False
    section_subject.save()
    return section_subject


def delete_section_subject_from_db(section_subject: SectionSubject) -> bool:
    """
    Delete section subject from database.
    
    This will also delete associated gradebooks if they exist and have no grades.
    If grades exist, this function should not be called - use section_subject_has_grades() first.
    """
    from django.db.models import ProtectedError
    from grading.models import GradeBook
    
    try:
        # Delete gradebooks first (they have protected FK to section_subject)
        # This is safe because we've already checked there are no grades
        gradebooks = GradeBook.objects.filter(section_subject=section_subject)
        gradebook_count = gradebooks.count()
        
        if gradebook_count > 0:
            logger.info(f"Deleting {gradebook_count} gradebook(s) for section subject: {section_subject.id}")
            gradebooks.delete()
        
        # Now delete the section subject
        logger.info(f"Deleting section subject: {section_subject.id}")
        section_subject.delete()
        return True
    except ProtectedError as e:
        logger.error(f"Cannot delete section subject: {section_subject.id}, protected by: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to delete section subject: {section_subject.id}, error: {e}")
        return False

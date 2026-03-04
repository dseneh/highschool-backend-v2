"""
Reusable gradebook initialization module.

This module provides a centralized, optimized function for initializing gradebooks
for an academic year. It handles:
1. Populating assessment types and grade letters from JSON fixtures
2. Populating default assessment templates (for multiple_entry mode)
3. Creating gradebooks for all sections
4. Generating assessments based on grading style (single_entry vs multiple_entry)
5. Creating grade entries for all enrolled students

Usage:
    from grading.gradebook_initializer import initialize_gradebooks_for_academic_year
    
    result = initialize_gradebooks_for_academic_year(
        academic_year=academic_year_instance,
        grading_style='multiple_entry',  # or 'single_entry'
        created_by=user_instance,
        regenerate=False,  # Set True to delete and recreate
        section_id=None  # Optional: limit to specific section
    )
"""

import json
import os
import logging
from decimal import Decimal
from typing import Optional, Dict, Any, List
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)

from academics.models import AcademicYear, Section, SectionSubject, MarkingPeriod
from students.models import Enrollment
from grading.models import (
    AssessmentType, DefaultAssessmentTemplate,
    GradeBook, Assessment, Grade, GradeLetter
)
from grading.utils import generate_assessments_for_gradebook_with_settings


def initialize_gradebooks_for_academic_year(
    academic_year: AcademicYear,
    grading_style: str = 'multiple_entry',
    created_by=None,
    regenerate: bool = False,
    section_id: Optional[str] = None,
    skip_assessment_types: bool = False,
    skip_grade_letters: bool = False,
    skip_templates: bool = False
) -> Dict[str, Any]:
    """
    Initialize gradebooks for an academic year with all necessary setup.
    
    This function performs complete gradebook initialization:
    1. Ensures assessment types exist (populates from fixture if needed)
    2. Ensures grade letters exist (populates from fixture if needed)
    3. Ensures default templates exist for multiple_entry mode
    4. Creates gradebooks for all section-subjects
    5. Generates assessments based on grading_style
    6. Creates grade entries for all enrolled students
    
    Args:
        academic_year: AcademicYear instance to create gradebooks for
        grading_style: 'single_entry' or 'multiple_entry'
        created_by: User instance for created_by/updated_by fields
        regenerate: If True, deletes existing gradebooks and recreates (DESTRUCTIVE)
        section_id: Optional UUID string to limit to specific section
        skip_assessment_types: Skip populating assessment types
        skip_grade_letters: Skip populating grade letters
        skip_templates: Skip populating default templates
        
    Returns:
        Dictionary with initialization statistics:
        {
            'success': bool,
            'message': str,
            'grading_style': str,
            'stats': {
                'assessment_types_created': int,
                'assessment_types_updated': int,
                'grade_letters_created': int,
                'grade_letters_updated': int,
                'templates_created': int,
                'templates_updated': int,
                'gradebooks_created': int,
                'gradebooks_skipped': int,
                'gradebooks_deleted': int,
                'assessments_created': int,
                'grades_created': int,
                'sections_processed': int
            },
            'errors': list
        }
    
    Example:
        >>> result = initialize_gradebooks_for_academic_year(
        ...     academic_year=ay_2024,
        ...     grading_style='single_entry',
        ...     created_by=admin_user,
        ...     regenerate=False
        ... )
        >>> print(f"Created {result['stats']['gradebooks_created']} gradebooks")
    """
    
    # Validate inputs
    if grading_style not in ['single_entry', 'multiple_entry']:
        return {
            'success': False,
            'message': f"Invalid grading_style: {grading_style}. Must be 'single_entry' or 'multiple_entry'.",
            'stats': {},
            'errors': ['Invalid grading_style parameter']
        }
    
    # Get system user if not provided
    # if created_by is None:
    #     from users.models import CustomUser
    #     created_by = CustomUser.objects.filter(is_superuser=True).first()
    #     if not created_by:
    #         created_by = CustomUser.objects.filter(is_staff=True).first()
    #     if not created_by:
    #         return {
    #             'success': False,
    #             'message': 'No admin user found. Please provide created_by parameter.',
    #             'stats': {},
    #             'errors': ['No admin user available']
    #         }
    
    stats = {
        'assessment_types_created': 0,
        'assessment_types_updated': 0,
        'grade_letters_created': 0,
        'grade_letters_updated': 0,
        'templates_created': 0,
        'templates_updated': 0,
        'gradebooks_created': 0,
        'gradebooks_skipped': 0,
        'gradebooks_deleted': 0,
        'assessments_created': 0,
        'grades_created': 0,
        'sections_processed': 0
    }
    
    errors = []
    
    try:
        # Steps 1-4: Run in single transaction (fixtures + gradebooks + assessments)
        with transaction.atomic():
            # Step 1: Ensure Assessment Types exist
            if not skip_assessment_types:
                type_result = _ensure_assessment_types(
                    grading_style=grading_style,
                    created_by=created_by
                )
                stats['assessment_types_created'] = type_result['created']
                stats['assessment_types_updated'] = type_result['updated']
                errors.extend(type_result.get('errors', []))
            
            # Step 2: Ensure Grade Letters exist
            if not skip_grade_letters:
                letter_result = _ensure_grade_letters(
                    created_by=created_by
                )
                stats['grade_letters_created'] = letter_result['created']
                stats['grade_letters_updated'] = letter_result['updated']
                errors.extend(letter_result.get('errors', []))
            
            # Step 3: Ensure Default Templates exist (only for multiple_entry)
            if grading_style == 'multiple_entry' and not skip_templates:
                template_result = _ensure_default_templates(
                    created_by=created_by
                )
                stats['templates_created'] = template_result['created']
                stats['templates_updated'] = template_result['updated']
                errors.extend(template_result.get('errors', []))
            
            # Step 4: Create/Regenerate Gradebooks and Assessments
            gradebook_result = _initialize_gradebooks(
                academic_year=academic_year,
                grading_style=grading_style,
                created_by=created_by,
                regenerate=regenerate,
                section_id=section_id
            )
            stats['gradebooks_created'] = gradebook_result['created']
            stats['gradebooks_skipped'] = gradebook_result['skipped']
            stats['gradebooks_deleted'] = gradebook_result['deleted']
            stats['assessments_created'] = gradebook_result['assessments_created']
            stats['sections_processed'] = gradebook_result['sections_processed']
            errors.extend(gradebook_result.get('errors', []))
        
        # Step 5: Create Grade Entries (OUTSIDE transaction, in chunks)
        # This prevents timeout on large datasets
        logger.info("Creating grade entries in separate transactions...")
        grade_result = _create_grade_entries_chunked(
            academic_year=academic_year,
            created_by=created_by,
            section_id=section_id
        )
        stats['grades_created'] = grade_result['created']
        errors.extend(grade_result.get('errors', []))
        
        return {
            'success': True,
            'message': f"Successfully initialized gradebooks for {academic_year.name} ({grading_style} mode)",
            'grading_style': grading_style,
            'stats': stats,
            'errors': errors
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f"Error during initialization: {str(e)}",
            'grading_style': grading_style,
            'stats': stats,
            'errors': errors + [str(e)]
        }


# ============================================================================
# PRIVATE HELPER FUNCTIONS
# ============================================================================

def _get_fixture_path(fixture_file: str) -> str:
    """Get the full path to a fixture file."""
    # Get grading app directory
    grading_app_dir = os.path.dirname(__file__)
    fixture_path = os.path.join(grading_app_dir, 'fixtures', fixture_file)
    
    if not os.path.exists(fixture_path):
        raise FileNotFoundError(f"Fixture file not found: {fixture_path}")
    
    return fixture_path


def _ensure_assessment_types(
    grading_style: str,
    created_by
) -> Dict[str, Any]:
    """
    Ensure assessment types exist, filtered by grading style.
    
    For single_entry: Only populate/update types where is_single_entry=True
    For multiple_entry: Only populate/update types where is_single_entry=False
    """
    try:
        fixture_path = _get_fixture_path('assessment_types.json')
        
        with open(fixture_path, 'r', encoding='utf-8') as file:
            types_data = json.load(file)
        
        created = 0
        updated = 0
        errors = []
        
        for type_data in types_data:
            try:
                name = type_data['name']
                description = type_data.get('description', '')
                is_single_entry = type_data.get('is_single_entry', False)
                
                # Filter by grading style
                if grading_style == 'single_entry' and not is_single_entry:
                    continue
                if grading_style == 'multiple_entry' and is_single_entry:
                    continue
                
                # Use get_or_create for atomic operation
                obj, was_created = AssessmentType.objects.get_or_create(
                    name=name,
                    defaults={
                        'description': description,
                        'is_single_entry': is_single_entry,
                        'created_by': created_by,
                        'updated_by': created_by,
                    }
                )
                
                if was_created:
                    created += 1
                elif obj.description != description or obj.is_single_entry != is_single_entry:
                    # Update if values changed
                    obj.description = description
                    obj.is_single_entry = is_single_entry
                    obj.updated_by = created_by
                    obj.save(update_fields=['description', 'is_single_entry', 'updated_by'])
                    updated += 1
                    
            except Exception as e:
                errors.append(f"Error processing assessment type '{type_data.get('name')}': {str(e)}")
        
        return {
            'created': created,
            'updated': updated,
            'errors': errors
        }
        
    except FileNotFoundError as e:
        return {
            'created': 0,
            'updated': 0,
            'errors': [str(e)]
        }
    except json.JSONDecodeError as e:
        return {
            'created': 0,
            'updated': 0,
            'errors': [f"Invalid JSON in assessment_types.json: {str(e)}"]
        }


def _ensure_grade_letters(created_by) -> Dict[str, Any]:
    """Ensure grade letters exist for the school."""
    try:
        fixture_path = _get_fixture_path('grade_letters.json')
        
        with open(fixture_path, 'r', encoding='utf-8') as file:
            letters_data = json.load(file)
        
        created = 0
        updated = 0
        errors = []
        
        for letter_data in letters_data:
            try:
                letter = letter_data['letter']
                min_percentage = Decimal(str(letter_data['min_percentage']))
                max_percentage = Decimal(str(letter_data['max_percentage']))
                order = letter_data.get('order', 0)
                
                # Use get_or_create for atomic operation
                obj, was_created = GradeLetter.objects.get_or_create(
                    letter=letter,
                    defaults={
                        'min_percentage': min_percentage,
                        'max_percentage': max_percentage,
                        'order': order,
                        'created_by': created_by,
                        'updated_by': created_by,
                    }
                )
                
                if was_created:
                    created += 1
                elif (obj.min_percentage != min_percentage or 
                      obj.max_percentage != max_percentage or
                      obj.order != order):
                    # Update if values changed
                    obj.min_percentage = min_percentage
                    obj.max_percentage = max_percentage
                    obj.order = order
                    obj.updated_by = created_by
                    obj.save(update_fields=['min_percentage', 'max_percentage', 'order', 'updated_by'])
                    updated += 1
                    
            except Exception as e:
                errors.append(f"Error processing grade letter '{letter_data.get('letter')}': {str(e)}")
        
        return {
            'created': created,
            'updated': updated,
            'errors': errors
        }
        
    except FileNotFoundError as e:
        return {
            'created': 0,
            'updated': 0,
            'errors': [str(e)]
        }
    except json.JSONDecodeError as e:
        return {
            'created': 0,
            'updated': 0,
            'errors': [f"Invalid JSON in grade_letters.json: {str(e)}"]
        }


def _ensure_default_templates(created_by) -> Dict[str, Any]:
    """Ensure default assessment templates exist (for multiple_entry mode)."""
    try:
        fixture_path = _get_fixture_path('default_assessments.json')
        
        with open(fixture_path, 'r', encoding='utf-8') as file:
            templates_data = json.load(file)
        
        created = 0
        updated = 0
        errors = []
        
        for template_data in templates_data:
            try:
                name = template_data['name']
                assessment_type_name = template_data['assessment_type']
                target = template_data.get('target', 'marking_period')
                
                # Get assessment type
                try:
                    assessment_type = AssessmentType.objects.get(
                        name=assessment_type_name
                    )
                except AssessmentType.DoesNotExist:
                    errors.append(
                        f"Assessment type '{assessment_type_name}' not found for template '{name}'. Skipping."
                    )
                    continue
                
                # Use get_or_create for atomic operation
                obj, was_created = DefaultAssessmentTemplate.objects.get_or_create(
                    name=name,
                    defaults={
                        'assessment_type': assessment_type,
                        'max_score': template_data['max_score'],
                        'weight': template_data['weight'],
                        'is_calculated': template_data.get('is_calculated', True),
                        'order': template_data.get('order', 0),
                        'description': template_data.get('description', ''),
                        'target': target,
                        'created_by': created_by,
                        'updated_by': created_by,
                    }
                )
                
                if was_created:
                    created += 1
                else:
                    # Update if values changed
                    needs_update = False
                    if obj.assessment_type != assessment_type:
                        obj.assessment_type = assessment_type
                        needs_update = True
                    if obj.max_score != template_data['max_score']:
                        obj.max_score = template_data['max_score']
                        needs_update = True
                    if obj.weight != template_data['weight']:
                        obj.weight = template_data['weight']
                        needs_update = True
                    if obj.is_calculated != template_data.get('is_calculated', True):
                        obj.is_calculated = template_data.get('is_calculated', True)
                        needs_update = True
                    if obj.order != template_data.get('order', 0):
                        obj.order = template_data.get('order', 0)
                        needs_update = True
                    if obj.description != template_data.get('description', ''):
                        obj.description = template_data.get('description', '')
                        needs_update = True
                    if obj.target != target:
                        obj.target = target
                        needs_update = True
                    
                    if needs_update:
                        obj.updated_by = created_by
                        obj.save()
                        updated += 1
                    
            except Exception as e:
                errors.append(f"Error processing template '{template_data.get('name')}': {str(e)}")
        
        return {
            'created': created,
            'updated': updated,
            'errors': errors
        }
        
    except FileNotFoundError as e:
        return {
            'created': 0,
            'updated': 0,
            'errors': [str(e)]
        }
    except json.JSONDecodeError as e:
        return {
            'created': 0,
            'updated': 0,
            'errors': [f"Invalid JSON in default_assessments.json: {str(e)}"]
        }


def _initialize_gradebooks(
    academic_year: AcademicYear,
    grading_style: str,
    created_by,
    regenerate: bool,
    section_id: Optional[str]
) -> Dict[str, Any]:
    """
    Create gradebooks for all section-subjects and generate assessments.
    
    This optimized function:
    1. Queries sections with select_related to minimize DB hits
    2. Bulk queries section-subjects
    3. Creates gradebooks and generates assessments
    4. Handles regeneration by deleting existing gradebooks
    """
    # Get sections
    # if section_id:
    #     sections = Section.objects.filter(
    #         id=section_id,
    #         grade_level__school=school
    #     ).select_related('grade_level')
    # else:
    sections = Section.objects.filter(
        active=True
    ).select_related('grade_level')
    
    created = 0
    skipped = 0
    deleted = 0
    assessments_created = 0
    sections_processed = 0
    errors = []
    
    # Batch process sections
    for section in sections:
        try:
            # Get all subjects for this section in one query
            section_subjects = SectionSubject.objects.filter(
                section=section
            ).select_related('subject', 'section')
            
            if not section_subjects.exists():
                errors.append(f"No subjects found for section: {section.name}")
                continue
            
            sections_processed += 1
            
            for section_subject in section_subjects:
                try:
                    # Check if gradebook exists
                    existing_gradebook = GradeBook.objects.filter(
                        section_subject=section_subject,
                        academic_year=academic_year
                    ).first()
                    
                    if existing_gradebook and not regenerate:
                        skipped += 1
                        continue
                    
                    if existing_gradebook and regenerate:
                        # Delete existing gradebook (cascades to assessments and grades)
                        existing_gradebook.delete()
                        deleted += 1
                    
                    # Create new gradebook
                    gradebook = GradeBook.objects.create(
                        section_subject=section_subject,
                        section=section,
                        subject=section_subject.subject,
                        academic_year=academic_year,
                        name=f'{section_subject.subject.name} - {section.name}',
                        calculation_method='weighted',
                        created_by=created_by,
                        updated_by=created_by
                    )
                    
                    # Generate assessments based on grading style
                    # The generate_assessments_for_gradebook_with_settings function
                    result = generate_assessments_for_gradebook_with_settings(gradebook, grading_style=grading_style)
                    assessments_count = result['assessments_created']
                    assessments_created += assessments_count
                    
                    created += 1
                    
                except Exception as e:
                    errors.append(
                        f"Error creating gradebook for {section_subject.subject.name} "
                        f"in {section.name}: {str(e)}"
                    )
                    
        except Exception as e:
            errors.append(f"Error processing section {section.name}: {str(e)}")
    
    return {
        'created': created,
        'skipped': skipped,
        'deleted': deleted,
        'assessments_created': assessments_created,
        'sections_processed': sections_processed,
        'errors': errors
    }


def _create_grade_entries(
    academic_year: AcademicYear,
    created_by,
    section_id: Optional[str]
) -> Dict[str, Any]:
    """
    Create grade entries for all students in all assessments.
    
    This optimized function:
    1. Queries assessments with select_related to minimize DB hits
    2. Batch queries enrollments per section
    3. Uses bulk_create for grade entries (when possible)
    4. Checks for existing grades to avoid duplicates
    """
    # Get all assessments for this academic year
    assessments = Assessment.objects.filter(
        gradebook__academic_year=academic_year,
        active=True
    ).select_related(
        'gradebook',
        'gradebook__section',
        'gradebook__subject'
    )
    
    if section_id:
        assessments = assessments.filter(gradebook__section_id=section_id)
    
    created = 0
    errors = []
    
    # Group assessments by section for efficient enrollment queries
    from collections import defaultdict
    assessments_by_section = defaultdict(list)
    
    for assessment in assessments:
        assessments_by_section[assessment.gradebook.section.id].append(assessment)
    
    # Process each section's assessments
    for section_id, section_assessments in assessments_by_section.items():
        try:
            section = section_assessments[0].gradebook.section
            
            # Get all enrollments for this section in one query
            enrollments = Enrollment.objects.filter(
                section_id=section_id,
                academic_year=academic_year
            ).select_related('student')
            
            # Prepare bulk create list for this section
            grades_to_create = []
            
            # Create grades for each assessment and enrollment
            for assessment in section_assessments:
                # Get existing student IDs for this assessment (optimized query)
                existing_student_ids = set(
                    Grade.objects.filter(assessment=assessment)
                    .values_list('student_id', flat=True)
                )
                
                for enrollment in enrollments:
                    # Check if grade already exists
                    if enrollment.student.id not in existing_student_ids:
                        grades_to_create.append(
                            Grade(
                                assessment=assessment,
                                enrollment=enrollment,
                                student=enrollment.student,
                                academic_year=academic_year,
                                section=section,
                                subject=assessment.gradebook.subject,
                                score=None,
                                status=None,
                                created_by=created_by,
                                updated_by=created_by
                            )
                        )
            
            # Bulk create all grades for this section (10-20x faster than individual creates)
            if grades_to_create:
                Grade.objects.bulk_create(grades_to_create, batch_size=500)
                created += len(grades_to_create)
                        
        except Exception as e:
            errors.append(f"Error processing section {section_id}: {str(e)}")
    
    return {
        'created': created,
        'errors': errors
    }


def _create_grade_entries_chunked(
    academic_year: AcademicYear,
    created_by,
    section_id: Optional[str],
    chunk_size: int = 1
) -> Dict[str, Any]:
    """
    Create grade entries in smaller transactions to prevent timeout.
    
    Processes sections ONE AT A TIME, committing after each to avoid
    long-running transactions that can timeout on production.
    
    Args:
        academic_year: Academic year to create grades for
        created_by: User creating the grades
        section_id: Optional section ID to limit processing
        chunk_size: Number of sections to process per transaction (default: 1)
    
    Returns:
        Dictionary with creation statistics and errors
    """
    from collections import defaultdict
    
    logger.info(f"Starting chunked grade entry creation (chunk_size={chunk_size})")
    
    # Get all assessments for this academic year
    assessments = Assessment.objects.filter(
        gradebook__academic_year=academic_year,
        active=True
    ).select_related(
        'gradebook',
        'gradebook__section',
        'gradebook__subject'
    )
    
    if section_id:
        assessments = assessments.filter(gradebook__section_id=section_id)
    
    # Group assessments by section
    assessments_by_section = defaultdict(list)
    for assessment in assessments:
        assessments_by_section[assessment.gradebook.section.id].append(assessment)
    
    total_created = 0
    total_errors = []
    section_ids = list(assessments_by_section.keys())
    total_sections = len(section_ids)
    
    logger.info(f"Processing {total_sections} sections one at a time to prevent timeout")
    
    # Process sections ONE AT A TIME
    for i, section_id in enumerate(section_ids):
        section_num = i + 1
        section_assessments = assessments_by_section[section_id]
        section = section_assessments[0].gradebook.section
        
        logger.info(f"Processing section {section_num}/{total_sections}: {section.name}")
        
        try:
            # Process this section in its own transaction
            with transaction.atomic():
                # Get enrollments for this section
                enrollments = Enrollment.objects.filter(
                    section_id=section_id,
                    academic_year=academic_year
                ).select_related('student')
                
                enrollment_count = enrollments.count()
                logger.info(f"  {len(section_assessments)} assessments × {enrollment_count} students = {len(section_assessments) * enrollment_count} potential grades")
                
                # Prepare grades for this section
                grades_to_create = []
                
                for assessment in section_assessments:
                    # Get existing student IDs
                    existing_student_ids = set(
                        Grade.objects.filter(assessment=assessment)
                        .values_list('student_id', flat=True)
                    )
                    
                    for enrollment in enrollments:
                        if enrollment.student.id not in existing_student_ids:
                            grades_to_create.append(
                                Grade(
                                    assessment=assessment,
                                    enrollment=enrollment,
                                    student=enrollment.student,
                                    academic_year=academic_year,
                                    section=section,
                                    subject=assessment.gradebook.subject,
                                    score=None,
                                    status=None,
                                    created_by=created_by,
                                    updated_by=created_by
                                )
                            )
                
                # Bulk create grades for this section with smaller batch size
                if grades_to_create:
                    Grade.objects.bulk_create(grades_to_create, batch_size=250)
                    total_created += len(grades_to_create)
                    logger.info(f"  ✓ Created {len(grades_to_create)} grades")
                else:
                    logger.info(f"  ✓ No new grades needed (all exist)")
            
            logger.info(f"Section {section_num}/{total_sections} complete")
                
        except Exception as e:
            error_msg = f"Error processing section {section.name}: {str(e)}"
            logger.exception(error_msg)
            total_errors.append(error_msg)
    
    logger.info(f"Chunked grade creation complete: {total_created} total grades created")
    
    return {
        'created': total_created,
        'errors': total_errors
    }


# ============================================================================
# PUBLIC HELPER FUNCTIONS
# ============================================================================

def get_initialization_preview(
    academic_year: AcademicYear,
    grading_style: str = 'multiple_entry',
    section_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Preview what would be created without actually creating anything.
    
    Useful for showing admins what will happen before confirming.
    
    Returns:
        Dictionary with preview information
    """
    # Get sections
    if section_id:
        sections = Section.objects.filter(
            id=section_id,
        ).select_related('grade_level')
    else:
        sections = Section.objects.filter(
            active=True
        ).select_related('grade_level')
    
    preview = {
        'grading_style': grading_style,
        'academic_year': academic_year.name,
        'sections_to_process': [],
        'estimated_gradebooks': 0,
        'estimated_assessments': 0,
        'estimated_grades': 0
    }
    
    # Count marking periods for assessment estimation
    marking_periods_count = MarkingPeriod.objects.filter(
        semester__academic_year=academic_year,
        active=True
    ).count()
    
    # Get templates count for multiple_entry mode
    if grading_style == 'multiple_entry':
        templates_count = DefaultAssessmentTemplate.objects.filter(
            is_active=True,
            target='marking_period'
        ).count()
        exam_templates_count = DefaultAssessmentTemplate.objects.filter(
            is_active=True,
            target='exam'
        ).count()
    else:
        templates_count = 1  # Single entry = 1 assessment per marking period
        exam_templates_count = 0
    
    for section in sections:
        section_subjects = SectionSubject.objects.filter(section=section)
        subject_count = section_subjects.count()
        
        # Count students
        student_count = Enrollment.objects.filter(
            section=section,
            academic_year=academic_year
        ).count()
        
        # Estimate assessments per gradebook
        assessments_per_gradebook = (templates_count * marking_periods_count) + exam_templates_count
        
        preview['sections_to_process'].append({
            'section_name': section.name,
            'subjects': subject_count,
            'students': student_count,
            'gradebooks_to_create': subject_count,
            'assessments_per_gradebook': assessments_per_gradebook,
            'total_assessments': subject_count * assessments_per_gradebook,
            'total_grades': subject_count * assessments_per_gradebook * student_count
        })
        
        preview['estimated_gradebooks'] += subject_count
        preview['estimated_assessments'] += subject_count * assessments_per_gradebook
        preview['estimated_grades'] += subject_count * assessments_per_gradebook * student_count
    
    return preview


def create_gradebook_for_section_subject(
    section_subject,
    academic_year: AcademicYear,
    grading_style: str = 'multiple_entry',
    created_by=None
) -> Dict[str, Any]:
    """
    Automatically create gradebook, assessments, and grades when a subject is added to a section.
    
    This function:
    1. Creates a gradebook for the section-subject combination
    2. Generates assessments based on grading style
    3. Creates grade entries for all currently enrolled students
    
    Args:
        section_subject: SectionSubject instance that was just created
        academic_year: AcademicYear instance to create gradebook for
        grading_style: 'single_entry' or 'multiple_entry' (default)
        created_by: User instance for audit fields
        
    Returns:
        Dictionary with creation statistics:
        {
            'success': bool,
            'gradebook_created': bool,
            'gradebook_id': str,
            'assessments_created': int,
            'grades_created': int,
            'errors': list
        }
    """
    result = {
        'success': False,
        'gradebook_created': False,
        'gradebook_id': None,
        'assessments_created': 0,
        'grades_created': 0,
        'errors': []
    }
    
    try:
        with transaction.atomic():
            # Check if gradebook already exists
            existing_gradebook = GradeBook.objects.filter(
                section_subject=section_subject,
                academic_year=academic_year
            ).first()
            
            if existing_gradebook:
                result['errors'].append(
                    f"Gradebook already exists for {section_subject.subject.name} "
                    f"in {section_subject.section.name}"
                )
                result['gradebook_id'] = str(existing_gradebook.id)
                return result
            
            # Create gradebook
            gradebook = GradeBook.objects.create(
                section_subject=section_subject,
                section=section_subject.section,
                subject=section_subject.subject,
                academic_year=academic_year,
                name=f'{section_subject.subject.name} - {section_subject.section.name}',
                calculation_method='weighted',
                created_by=created_by,
                updated_by=created_by
            )
            result['gradebook_created'] = True
            result['gradebook_id'] = str(gradebook.id)
            
            logger.info(
                f"Created gradebook {gradebook.id} for {section_subject.subject.name} "
                f"in {section_subject.section.name}"
            )
            
            # Generate assessments based on grading style
            try:
                assessment_result = generate_assessments_for_gradebook_with_settings(
                    gradebook,
                    grading_style=grading_style
                )
                result['assessments_created'] = assessment_result.get('assessments_created', 0)
                
                logger.info(
                    f"Created {result['assessments_created']} assessments for gradebook {gradebook.id}"
                )
            except Exception as e:
                result['errors'].append(f"Error generating assessments: {str(e)}")
                logger.error(f"Error generating assessments for gradebook {gradebook.id}: {str(e)}")
            
            # Create grade entries for all enrolled students
            try:
                # Get all assessments for this gradebook
                assessments = Assessment.objects.filter(
                    gradebook=gradebook,
                    active=True
                )
                
                # Get all enrollments for this section in this academic year
                enrollments = Enrollment.objects.filter(
                    section=section_subject.section,
                    academic_year=academic_year
                ).select_related('student')
                
                # Create grades in bulk
                grades_to_create = []
                for assessment in assessments:
                    for enrollment in enrollments:
                        grades_to_create.append(
                            Grade(
                                assessment=assessment,
                                enrollment=enrollment,
                                student=enrollment.student,
                                academic_year=academic_year,
                                section=section_subject.section,
                                subject=section_subject.subject,
                                score=None,
                                status=None,
                                created_by=created_by,
                                updated_by=created_by
                            )
                        )
                
                if grades_to_create:
                    Grade.objects.bulk_create(grades_to_create, batch_size=500)
                    result['grades_created'] = len(grades_to_create)
                    
                    logger.info(
                        f"Created {result['grades_created']} grade entries for gradebook {gradebook.id}"
                    )
            except Exception as e:
                result['errors'].append(f"Error creating grade entries: {str(e)}")
                logger.error(f"Error creating grade entries for gradebook {gradebook.id}: {str(e)}")
            
            result['success'] = True
            
    except Exception as e:
        result['errors'].append(f"Error creating gradebook: {str(e)}")
        logger.error(
            f"Error in create_gradebook_for_section_subject: {str(e)}", 
            exc_info=True
        )
    
    return result

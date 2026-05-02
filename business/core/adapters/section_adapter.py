"""
Section Django Adapter

Django-specific database operations for sections.
"""

from typing import Optional, List, Dict, Any
from django.db import transaction
from pathlib import Path
import json

from academics.models import Section, GradeLevel, Period, SectionTimeSlot, SectionSubject
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
                        source_section_id: Optional[str] = None,
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

    initialize_section_time_slots(
        section=section,
        source_section_id=source_section_id,
        user=user,
        replace_existing=True,
    )

    if source_section_id:
        copy_section_subjects_and_fees(
            source_section_id=source_section_id,
            target_section=section,
            user=user,
        )
    
    return section


@transaction.atomic
def copy_section_subjects_and_fees(
    source_section_id: str,
    target_section: Section,
    user=None,
) -> tuple[int, int, int, int]:
    """
    Clone subjects, fees, gradebooks and assessments from an existing section.

    Returns:
        (subject_count, fee_count, gradebook_count, assessment_count)
    """
    source_section = Section.objects.filter(id=source_section_id, active=True).first()
    if not source_section:
        return 0, 0, 0, 0

    # ── 1. Clone subjects, tracking old→new SectionSubject mapping ────────────
    # Maps source SectionSubject.id → newly created SectionSubject
    old_ss_to_new_ss: Dict[str, "SectionSubject"] = {}
    subject_count = 0
    for old_ss in source_section.section_subjects.filter(active=True).select_related("subject"):
        new_ss = SectionSubject.objects.create(
            section=target_section,
            subject=old_ss.subject,
            created_by=user,
            updated_by=user,
        )
        old_ss_to_new_ss[str(old_ss.id)] = new_ss
        subject_count += 1

    # ── 2. Clone fees ──────────────────────────────────────────────────────────
    from finance.models import SectionFee

    fee_count = 0
    for section_fee in source_section.section_fees.filter(active=True).select_related("general_fee"):
        SectionFee.objects.create(
            section=target_section,
            general_fee=section_fee.general_fee,
            amount=section_fee.amount,
            created_by=user,
            updated_by=user,
        )
        fee_count += 1

    # ── 3. Clone gradebooks + assessments ─────────────────────────────────────
    if not old_ss_to_new_ss:
        return subject_count, fee_count, 0, 0

    from grading.models import GradeBook, Assessment

    gradebook_count = 0
    assessment_count = 0

    # Fetch all source gradebooks in one query (across all SectionSubjects)
    source_gradebooks = (
        GradeBook.objects
        .filter(
            section_subject_id__in=old_ss_to_new_ss.keys(),
            active=True,
        )
        .prefetch_related(
            "assessments"
        )
        .select_related("academic_year", "section_subject")
    )

    for src_gb in source_gradebooks:
        new_ss = old_ss_to_new_ss.get(str(src_gb.section_subject_id))
        if new_ss is None:
            continue

        # Build the new gradebook name by replacing the source section name
        gb_name = src_gb.name.replace(
            source_section.name, target_section.name, 1
        ) if source_section.name in src_gb.name else src_gb.name

        # Guard against the unique_together constraint:
        # (section_subject, academic_year, name) must be unique.
        if GradeBook.objects.filter(
            section_subject=new_ss,
            academic_year=src_gb.academic_year,
            name=gb_name,
        ).exists():
            continue

        new_gb = GradeBook.objects.create(
            section_subject=new_ss,
            section=target_section,
            subject=new_ss.subject,
            academic_year=src_gb.academic_year,
            name=gb_name,
            calculation_method=src_gb.calculation_method,
            created_by=user,
            updated_by=user,
        )
        gradebook_count += 1

        # Clone assessments (structure only — no student grades)
        for src_asmt in src_gb.assessments.filter(active=True):
            Assessment.objects.create(
                gradebook=new_gb,
                name=src_asmt.name,
                assessment_type=src_asmt.assessment_type,
                marking_period=src_asmt.marking_period,
                max_score=src_asmt.max_score,
                weight=src_asmt.weight,
                due_date=src_asmt.due_date,
                is_calculated=src_asmt.is_calculated,
                created_by=user,
                updated_by=user,
            )
            assessment_count += 1

    return subject_count, fee_count, gradebook_count, assessment_count


def _load_default_section_timetable_template() -> Dict[str, Any]:
    template_path = (
        Path(__file__).resolve().parents[3]
        / "academics"
        / "defaults"
        / "section_time_slots.template.json"
    )

    if not template_path.exists():
        raise FileNotFoundError(
            "Default section timetable template not found at "
            f"{template_path}"
        )

    with template_path.open("r", encoding="utf-8") as template_file:
        return json.load(template_file)


def _get_or_create_period(name: str, period_type: str, user=None) -> Period:
    period = Period.objects.filter(name__iexact=name).first()
    if period:
        return period

    return Period.objects.create(
        name=name,
        period_type=period_type or Period.PeriodType.CLASS,
        created_by=user,
        updated_by=user,
    )


@transaction.atomic
def seed_section_time_slots_from_template(section: Section, user=None) -> int:
    template = _load_default_section_timetable_template()
    slots = template.get("slots") or []
    created_count = 0

    for slot in slots:
        period_name = slot.get("period")
        if not period_name:
            continue

        period_type = slot.get("period_type") or Period.PeriodType.CLASS
        period = _get_or_create_period(period_name, period_type, user=user)

        day_values = slot.get("days") or [slot.get("day_of_week")]
        day_values = [day for day in day_values if day]
        if not day_values:
            continue

        for day_of_week in day_values:
            section.time_slots.create(
                period=period,
                day_of_week=day_of_week,
                start_time=slot.get("start_time"),
                end_time=slot.get("end_time"),
                sort_order=slot.get("sort_order") or 1,
                created_by=user,
                updated_by=user,
            )
            created_count += 1

    return created_count


@transaction.atomic
def copy_section_time_slots(source_section: Section, target_section: Section, user=None) -> int:
    source_slots = source_section.time_slots.filter(active=True).order_by(
        "day_of_week", "sort_order", "start_time"
    )
    created_count = 0

    for slot in source_slots:
        SectionTimeSlot.objects.create(
            section=target_section,
            period=slot.period,
            day_of_week=slot.day_of_week,
            start_time=slot.start_time,
            end_time=slot.end_time,
            sort_order=slot.sort_order,
            created_by=user,
            updated_by=user,
        )
        created_count += 1

    return created_count


@transaction.atomic
def initialize_section_time_slots(
    section: Section,
    source_section_id: Optional[str] = None,
    user=None,
    replace_existing: bool = True,
) -> tuple[int, str]:
    if replace_existing:
        section.time_slots.all().delete()

    source_section: Optional[Section] = None

    if source_section_id:
        source_section = Section.objects.filter(
            id=source_section_id,
            active=True,
        ).first()

    if source_section is None and section.grade_level_id:
        source_section = (
            Section.objects.filter(
                grade_level_id=section.grade_level_id,
                active=True,
                time_slots__active=True,
            )
            .exclude(id=section.id)
            .distinct()
            .first()
        )

    if source_section:
        count = copy_section_time_slots(source_section, section, user=user)
        return count, f"section:{source_section.id}"

    count = seed_section_time_slots_from_template(section, user=user)
    return count, "template:default"


@transaction.atomic
def regenerate_section_time_slots_from_template(section: Section, user=None) -> tuple[int, str]:
    section.time_slots.all().delete()
    count = seed_section_time_slots_from_template(section, user=user)
    return count, "template:default"


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

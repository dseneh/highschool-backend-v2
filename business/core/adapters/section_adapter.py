"""
Section Django Adapter

Django-specific database operations for sections.
"""

from typing import Optional, List, Dict, Any
from django.db import transaction
from pathlib import Path
import json

from academics.models import Section, GradeLevel, Period, SectionTimeSlot
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
    
    return section


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

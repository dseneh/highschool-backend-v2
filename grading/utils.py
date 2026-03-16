from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from django.core.cache import cache
from django.db.models import Q
from django.db.utils import ProgrammingError, OperationalError

from .models import GradeBook, Grade, GradeLetter
from students.models import Enrollment


# ------------------------ Database-Driven Grade Letter System ------------------------


def get_letter_grade(percentage: Optional[float]) -> str:
    """
    Convert percentage to letter grade using school's grade letters.

    Args:
        percentage: The percentage score (0-100)

    Returns:
        Letter grade string

    Example:
        get_letter_grade(87.5)  # Returns "B+" based on school's letters
    """
    if percentage is None:
        return "N/A"

    # Convert Decimal to float if needed
    if hasattr(percentage, "quantize"):
        percentage = float(percentage)

    # Use the GradeLetter model method
    return GradeLetter.get_letter_for_percentage(percentage)


def create_standard_grade_letters():
    """
    Create standard US grade letters.
    This is useful for initial setup or as a fallback.

    Returns:
        List of GradeLetter instances
    """
    # Delete existing grade letters for this school
    GradeLetter.objects.all().delete()

    # Create the standard grade letters
    standard_letters = [
        ("A+", 97, 100, 1),
        ("A", 93, 96.99, 2),
        ("A-", 90, 92.99, 3),
        ("B+", 87, 89.99, 4),
        ("B", 83, 86.99, 5),
        ("B-", 80, 82.99, 6),
        ("C+", 77, 79.99, 7),
        ("C", 73, 76.99, 8),
        ("C-", 70, 72.99, 9),
        ("D+", 67, 69.99, 10),
        ("D", 63, 66.99, 11),
        ("D-", 60, 62.99, 12),
        ("F", 0, 59.99, 13),
    ]

    created_letters = []
    for letter, min_pct, max_pct, order in standard_letters:
        grade_letter = GradeLetter.objects.create(
            letter=letter,
            min_percentage=Decimal(str(min_pct)),
            max_percentage=Decimal(str(max_pct)),
            order=order,
        )
        created_letters.append(grade_letter)

    return created_letters


def get_grade_letters_for_school() -> dict:
    """
    Get grade letters as a dictionary.

    Returns:
        Dictionary with grade letters as keys and min/max ranges as values
    """
    from django.db import connection
    schema_name = connection.schema_name
    # Check cache first
    cache_key = f"grade_letters_school_{schema_name}"
    cached_letters = cache.get(cache_key)
    if cached_letters is not None:
        return cached_letters

    # Get from database
    grade_letters = GradeLetter.objects.all().order_by("order")

    # Convert to dictionary format
    letters_dict = {}
    for grade_letter in grade_letters:
        letters_dict[grade_letter.letter] = {
            "min": float(grade_letter.min_percentage),
            "max": float(grade_letter.max_percentage),
            "order": grade_letter.order,
        }

    # Cache for 30 minutes
    cache.set(cache_key, letters_dict, 1800)
    return letters_dict


def validate_grade_letters(grade_letters_data: list) -> tuple[bool, str]:
    """
    Validate that grade letters data has proper structure and no overlapping ranges.

    Args:
        grade_letters_data: List of dictionaries with letter, min_percentage, max_percentage

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    if not isinstance(grade_letters_data, list):
        return False, "Grade letters data must be a list"

    if not grade_letters_data:
        return False, "Grade letters data cannot be empty"

    # Validate each grade letter entry
    for i, letter_data in enumerate(grade_letters_data):
        if not isinstance(letter_data, dict):
            return False, f"Grade letter {i} must be a dictionary"

        required_fields = ["letter", "min_percentage", "max_percentage"]
        for field in required_fields:
            if field not in letter_data:
                return False, f"Grade letter {i} must have '{field}' field"

        # Validate percentage ranges
        try:
            min_pct = float(letter_data["min_percentage"])
            max_pct = float(letter_data["max_percentage"])
        except (ValueError, TypeError):
            return False, f"Grade letter {i} percentages must be numeric"

        if min_pct > max_pct:
            return (
                False,
                f"Grade letter {i} ({letter_data['letter']}) min percentage cannot be greater than max",
            )

        if min_pct < 0 or max_pct > 100:
            return (
                False,
                f"Grade letter {i} ({letter_data['letter']}) percentages must be between 0 and 100",
            )

    # Check for overlapping ranges
    sorted_letters = sorted(grade_letters_data, key=lambda x: x["min_percentage"])
    for i in range(len(sorted_letters) - 1):
        current = sorted_letters[i]
        next_letter = sorted_letters[i + 1]

        if current["max_percentage"] >= next_letter["min_percentage"]:
            return (
                False,
                f"Grade letters {current['letter']} and {next_letter['letter']} have overlapping ranges",
            )

    return True, ""


# ------------------------ Existing helpers ------------------------


def parse_decimal(val, field_name: str) -> Decimal:
    try:
        return Decimal(str(val))
    except Exception:
        raise ValueError(f"Invalid decimal for '{field_name}'.")


def paginate_qs(qs, request):
    """
    Paginate a queryset using page-based pagination instead of limit/offset.

    Args:
        qs: Django QuerySet to paginate
        request: HTTP request object with query parameters

    Returns:
        tuple: (paginated_queryset, meta_dict)

    Query parameters:
        - page: Page number (default: 1)
        - page_size: Items per page (default: 50, max: 200)

    Example:
        ?page=2&page_size=25
    """
    try:
        page_size = int(request.query_params.get("page_size", "50"))
        page_size = max(1, min(page_size, 200))  # Limit between 1 and 200
    except ValueError:
        page_size = 50

    try:
        page = int(request.query_params.get("page", "1"))
        page = max(1, page)  # Ensure page is at least 1
    except ValueError:
        page = 1

    # Calculate offset from page number
    offset = (page - 1) * page_size

    # Get total count
    total = qs.count()

    # Calculate pagination metadata
    total_pages = (total + page_size - 1) // page_size  # Ceiling division
    has_next = page < total_pages
    has_previous = page > 1

    # Apply pagination to queryset
    paginated_qs = qs[offset : offset + page_size]

    meta = {
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_previous": has_previous,
        "next_page": page + 1 if has_next else None,
        "previous_page": page - 1 if has_previous else None,
    }

    return paginated_qs, meta


def can_edit_grade_status(current: str) -> bool:
    return current in [Grade.Status.DRAFT, None, Grade.Status.REJECTED]


def is_valid_transition(
    current: str, 
    target: str, 
    require_review: bool = True, 
    require_approval: bool = True
) -> bool:
    """
    Check if a grade status transition is valid based on grading settings.
    
    Args:
        current: Current grade status
        target: Target grade status
        require_review: Whether grade review is required (default: True)
        require_approval: Whether grade approval is required (default: True)
        
    Returns:
        True if transition is valid, False otherwise
        
    Workflow:
    - With review & approval: draft → pending → reviewed → submitted → approved
    - Without review: draft → pending → submitted → approved (skip reviewed)
    - Without approval: draft → pending → reviewed → submitted (final, no approval)
    - Without both: draft → pending → submitted (final, skip reviewed and approval)
    """
    # FROM DRAFT/REJECTED/NULL TO PENDING
    if (current in [None, Grade.Status.DRAFT, Grade.Status.REJECTED] 
        and target == Grade.Status.PENDING):
        return True
    
    # FROM PENDING
    if current == Grade.Status.PENDING:
        # Always allow going back to draft or reject
        if target in (Grade.Status.DRAFT, Grade.Status.REJECTED):
            return True
        # If review required, go to reviewed
        if require_review and target == Grade.Status.REVIEWED:
            return True
        # If review not required, skip directly to submitted
        if not require_review and target == Grade.Status.SUBMITTED:
            return True
    
    # FROM REVIEWED
    if current == Grade.Status.REVIEWED:
        # Always allow going back
        if target in (Grade.Status.DRAFT, Grade.Status.REJECTED, Grade.Status.PENDING):
            return True
        # Go to submitted
        if target == Grade.Status.SUBMITTED:
            return True
    
    # FROM SUBMITTED
    if current == Grade.Status.SUBMITTED:
        # Always allow going back
        if target in (Grade.Status.DRAFT, Grade.Status.REJECTED):
            return True
        # If approval required, go to approved
        if require_approval and target == Grade.Status.APPROVED:
            return True
    
    # FROM APPROVED (only back to draft)
    if current == Grade.Status.APPROVED and target == Grade.Status.DRAFT:
        return True
    
    return False


def resolve_enrollment_for_gradebook(
    *, student_id: str, gradebook: GradeBook
) -> Optional[Enrollment]:
    """
    Find the student's Enrollment for the gradebook's academic year.
    Your schema guarantees at most one (unique student+academic_year).
    Ensure its section matches the GB's SectionSubject.section.
    """
    ss = gradebook.section_subject
    try:
        enrollment = Enrollment.objects.select_related("section").get(
            student_id=student_id,
            academic_year_id=gradebook.academic_year_id,
        )
    except Enrollment.DoesNotExist:
        return None

    if hasattr(ss, "section_id") and enrollment.section_id != ss.section_id:
        return None

    return enrollment


# ============================================================================
# DEFAULT ASSESSMENT GENERATION
# ============================================================================


def generate_assessments_for_gradebook_with_settings(
    gradebook: GradeBook, grading_style=None, created_by=None
) -> dict:
    """
    Generate assessments for a gradebook based on school/academic year settings.

    This is the main entry point for assessment generation that respects settings:
    - Single Entry Mode: Creates one "Final Grade" assessment per marking period
    - Multiple Entry Mode: Uses default assessment templates

    Args:
        gradebook: GradeBook instance to generate assessments for
        created_by: User who triggered the generation (optional)

    Returns:
        Dictionary with generation results:
        {
            'mode': 'single_entry' or 'multiple_entry',
            'assessments_created': int,
            'assessment_ids': list of UUIDs,
            'message': str
        }
    """
    from .models import Assessment, AssessmentType
    from academics.models import MarkingPeriod

    ay = gradebook.academic_year

    if not grading_style:
        try:
            grading_settings = GradingSettings.objects.first()
            grading_style = grading_settings.grading_style if grading_settings else "multiple_entry"
        except:
            # Default to multiple entry if no settings exist
            grading_style = "multiple_entry"

    created_assessments = []
    mode = grading_style

    if grading_style == "single_entry":
        # SINGLE ENTRY MODE: Create one assessment per marking period

        # Get assessment name from settings
        try:
            from settings.models import GradingSettings

            grading_settings = GradingSettings.objects.first()
            assessment_name = (
                grading_settings.single_entry_assessment_name if grading_settings else "Final Grade"
            ) or "Final Grade"
        except:
            assessment_name = "Final Grade"

        # Try to get existing single-entry type or one matching the name
        single_entry_type = AssessmentType.objects.filter(
            is_single_entry=True, active=True
        ).first()

        if not single_entry_type:
            # Try to find by name match
            single_entry_type = AssessmentType.objects.filter(
                name=assessment_name, active=True
            ).first()

            if single_entry_type:
                # Update existing type to be single-entry
                single_entry_type.is_single_entry = True
                single_entry_type.save(update_fields=["is_single_entry"])
            else:
                # Create new single-entry type
                single_entry_type = AssessmentType.objects.create(
                    name=assessment_name,
                    description="Single entry final grade assessment",
                    is_single_entry=True,
                    created_by=created_by or gradebook.created_by,
                )

        # Get all marking periods for this academic year
        marking_periods = MarkingPeriod.objects.filter(
            semester__academic_year=ay, active=True
        ).order_by("start_date")

        for mp in marking_periods:
            # Check if assessment already exists
            existing = Assessment.objects.filter(
                gradebook=gradebook,
                marking_period=mp,
                assessment_type=single_entry_type,
            ).first()

            if existing:
                continue

            # Create single assessment for this marking period
            assessment = Assessment.objects.create(
                gradebook=gradebook,
                name=f"{assessment_name}",
                assessment_type=single_entry_type,
                marking_period=mp,
                max_score=100,  # Standard 100-point scale
                weight=1,
                due_date=mp.end_date,  # Due at end of marking period
                is_calculated=True,
                created_by=created_by or gradebook.created_by,
            )

            created_assessments.append(assessment)

    else:
        # MULTIPLE ENTRY MODE: Use default assessment templates
        created_assessments = generate_default_assessments_for_gradebook(
            gradebook, created_by
        )

    return {
        "mode": mode,
        "assessments_created": len(created_assessments),
        "assessment_ids": [str(a.id) for a in created_assessments],
        "message": f"Generated {len(created_assessments)} assessments in {mode} mode",
    }


def create_gradebook_with_assessments(
    section_subject,
    academic_year,
    name,
    calculation_method,
    created_by,
    auto_generate=True,
):
    """
    Create a gradebook and optionally auto-generate assessments.

    This is a convenience function that combines gradebook creation with
    automatic assessment generation based on school settings.

    Args:
        section_subject: SectionSubject instance
        academic_year: AcademicYear instance
        name: Name for the gradebook
        calculation_method: Calculation method (average/weighted/cumulative)
        created_by: User creating the gradebook
        auto_generate: Whether to automatically generate assessments (default: True)

    Returns:
        dict with:
        {
            'gradebook': GradeBook instance,
            'assessments_generated': bool,
            'generation_result': dict (if assessments were generated)
        }
    """
    # Create the gradebook
    gradebook = GradeBook.objects.create(
        section_subject=section_subject,
        section=section_subject.section,
        subject=section_subject.subject,
        academic_year=academic_year,
        name=name,
        calculation_method=calculation_method,
        created_by=created_by,
        updated_by=created_by,
    )

    result = {
        "gradebook": gradebook,
        "assessments_generated": False,
        "generation_result": None,
    }

    if auto_generate:
        # Automatically generate assessments based on settings
        generation_result = generate_assessments_for_gradebook_with_settings(
            gradebook, created_by=created_by
        )
        result["assessments_generated"] = True
        result["generation_result"] = generation_result

    return result


def generate_default_assessments_for_gradebook(
    gradebook: GradeBook, created_by=None
) -> list:
    """
    Generate Assessment instances from DefaultAssessmentTemplate for a specific gradebook.

    This function:
    1. Gets all active templates for the gradebook's school
    2. For each marking period in the academic year:
       - Determines if marking period is an exam period (by checking if 'exam' is in name)
       - Matches templates to marking periods based on the 'target' field
       - Creates Assessment instances from matching templates
    3. Avoids duplicates by checking if assessment already exists

    Args:
        gradebook: GradeBook instance to generate assessments for
        created_by: User who triggered the generation (optional)

    Returns:
        List of created Assessment instances
    """
    from .models import DefaultAssessmentTemplate, Assessment
    from academics.models import MarkingPeriod

    ay = gradebook.academic_year

    # Get all active templates (templates are NOT year-specific)
    templates = DefaultAssessmentTemplate.objects.filter(
        is_active=True
    ).select_related("assessment_type")

    if not templates.exists():
        return []

    # Get all marking periods for this academic year
    marking_periods = MarkingPeriod.objects.filter(
        semester__academic_year=ay, active=True
    ).order_by("start_date")

    created_assessments = []

    for mp in marking_periods:
        # Determine if this is an exam marking period (by checking if 'exam' is in the name)
        is_exam_period = "exam" in mp.name.lower()

        # Get templates that match this marking period type
        for template in templates:
            # Skip if target doesn't match marking period type
            if is_exam_period and template.target != "exam":
                continue
            if not is_exam_period and template.target == "exam":
                continue

            # Check if this assessment already exists to avoid duplicates
            existing = Assessment.objects.filter(
                gradebook=gradebook,
                name=template.name,
                marking_period=mp,
                assessment_type=template.assessment_type,
            ).first()

            if existing:
                # Already exists, skip
                continue

            # Create assessment from template
            # Due date defaults to marking period end date
            due_date = mp.end_date

            assessment = Assessment.objects.create(
                gradebook=gradebook,
                name=template.name,
                assessment_type=template.assessment_type,
                marking_period=mp,
                max_score=template.max_score,
                weight=template.weight,
                due_date=due_date,
                is_calculated=template.is_calculated,
                created_by=created_by or gradebook.created_by,
            )

            created_assessments.append(assessment)

    return created_assessments


def generate_default_assessments_for_academic_year(
    academic_year, created_by=None
) -> dict:
    """
    Bulk generate assessments for all gradebooks in an academic year.
    Uses settings-aware generation to respect grading style configuration.

    This is useful when:
    - A new academic year is activated
    - New templates are created mid-year and need to be applied to all gradebooks
    - Manual bulk generation is triggered by admin

    Args:
        academic_year: AcademicYear instance
        created_by: User who triggered the generation (optional)

    Returns:
        Dictionary with statistics:
        {
            'gradebooks_processed': int,
            'assessments_created': int,
            'single_entry_gradebooks': int,
            'multiple_entry_gradebooks': int,
            'gradebooks_with_errors': list
        }
    """
    # Get all gradebooks for this academic year
    gradebooks = GradeBook.objects.filter(
        academic_year=academic_year, active=True
    ).select_related("section")

    stats = {
        "gradebooks_processed": 0,
        "assessments_created": 0,
        "single_entry_gradebooks": 0,
        "multiple_entry_gradebooks": 0,
        "gradebooks_with_errors": [],
    }

    for gradebook in gradebooks:
        try:
            # Use settings-aware generation
            result = generate_assessments_for_gradebook_with_settings(
                gradebook, created_by
            )
            stats["gradebooks_processed"] += 1
            stats["assessments_created"] += result["assessments_created"]

            # Track mode distribution
            if result["mode"] == "single_entry":
                stats["single_entry_gradebooks"] += 1
            else:
                stats["multiple_entry_gradebooks"] += 1

        except Exception as e:
            stats["gradebooks_with_errors"].append(
                {
                    "gradebook_id": str(gradebook.id),
                    "gradebook_name": gradebook.name,
                    "error": str(e),
                }
            )

    return stats


def regenerate_assessments_for_academic_year(
    academic_year, created_by=None, override_existing=False
) -> dict:
    """
    Regenerate assessments for an academic year by deleting all existing assessments
    and creating them fresh from templates.

    SAFETY CHECKS:
    1. Verifies templates exist before deletion
    2. Checks for existing grades (non-null scores)
    3. Requires override_existing=True if grades exist

    Args:
        academic_year: AcademicYear instance
        created_by: User who triggered the regeneration
        override_existing: If True, allows deletion even if grades exist (DANGEROUS!)

    Returns:
        Dictionary with statistics:
        {
            'templates_found': int,
            'gradebooks_processed': int,
            'assessments_deleted': int,
            'assessments_created': int,
            'grades_affected': int,
            'gradebooks_with_errors': list
        }

    Raises:
        ValueError: If no templates found or if grades exist without override
    """
    from .models import DefaultAssessmentTemplate, Assessment, Grade, GradeBook

    # Check 1: Verify templates exist
    templates = DefaultAssessmentTemplate.objects.filter(is_active=True)

    if not templates.exists():
        raise ValueError(
            "No active templates found. Please create templates before regenerating assessments."
        )

    # Get all gradebooks for this academic year
    gradebooks = GradeBook.objects.filter(
        academic_year=academic_year, active=True
    ).select_related("section_subject__section")

    if not gradebooks.exists():
        return {
            "templates_found": templates.count(),
            "gradebooks_processed": 0,
            "assessments_deleted": 0,
            "assessments_created": 0,
            "grades_affected": 0,
            "gradebooks_with_errors": [],
        }

    # Check 2: Check for existing grades
    existing_assessments = Assessment.objects.filter(
        gradebook__in=gradebooks, active=True
    )

    # Count grades with non-null scores
    grades_with_scores = Grade.objects.filter(
        assessment__in=existing_assessments, score__isnull=False
    ).count()

    if grades_with_scores > 0 and not override_existing:
        raise ValueError(
            f"Cannot regenerate: {grades_with_scores} grades with scores exist. "
            f"Pass 'override_existing=true' to force deletion (WARNING: This will delete all grades!)."
        )

    stats = {
        "templates_found": templates.count(),
        "gradebooks_processed": 0,
        "assessments_deleted": 0,
        "assessments_created": 0,
        "grades_affected": grades_with_scores,
        "gradebooks_with_errors": [],
    }

    # Proceed with deletion and regeneration
    for gradebook in gradebooks:
        try:
            # Delete all assessments for this gradebook
            assessments_to_delete = Assessment.objects.filter(
                gradebook=gradebook, active=True
            )

            deleted_count = assessments_to_delete.count()
            assessments_to_delete.delete()

            # Regenerate from templates
            created = generate_default_assessments_for_gradebook(gradebook, created_by)

            stats["gradebooks_processed"] += 1
            stats["assessments_deleted"] += deleted_count
            stats["assessments_created"] += len(created)

        except Exception as e:
            stats["gradebooks_with_errors"].append(
                {
                    "gradebook_id": str(gradebook.id),
                    "gradebook_name": gradebook.name,
                    "error": str(e),
                }
            )

    return stats


def preview_default_assessments_for_gradebook(gradebook: GradeBook) -> dict:
    """
    Preview what assessments would be generated for a gradebook without creating them.

    Useful for:
    - Showing admin what will be created before confirming
    - Testing template configurations
    - API endpoints that need to show what would happen

    Args:
        gradebook: GradeBook instance

    Returns:
        Dictionary with preview information:
        {
            'will_create': [
                {
                    'name': str,
                    'type': str,
                    'marking_period': str,
                    'max_score': Decimal,
                    'weight': Decimal,
                    'due_date': date or None,
                    'target': str
                }
            ],
            'already_exists': [similar structure],
            'skipped_by_target_mismatch': [similar structure with 'reason']
        }
    """
    from .models import DefaultAssessmentTemplate, Assessment
    from academics.models import MarkingPeriod

    ay = gradebook.academic_year

    templates = DefaultAssessmentTemplate.objects.filter(
        is_active=True
    ).select_related("assessment_type")

    marking_periods = MarkingPeriod.objects.filter(
        semester__academic_year=ay, active=True
    ).order_by("start_date")

    preview = {
        "will_create": [],
        "already_exists": [],
        "skipped_by_target_mismatch": [],
    }

    for mp in marking_periods:
        # Determine if this is an exam marking period
        is_exam_period = "exam" in mp.name.lower()

        for template in templates:
            assessment_info = {
                "name": template.name,
                "type": template.assessment_type.name,
                "marking_period": mp.name,
                "max_score": float(template.max_score),
                "weight": float(template.weight),
                "due_date": mp.end_date,
                "target": template.target,
                "is_exam_period": is_exam_period,
            }

            # Check target match
            if is_exam_period and template.target != "exam":
                assessment_info["reason"] = (
                    f"Template target is '{template.target}' but marking period is an exam period"
                )
                preview["skipped_by_target_mismatch"].append(assessment_info)
                continue

            if not is_exam_period and template.target == "exam":
                assessment_info["reason"] = (
                    f"Template target is 'exam' but marking period is a regular marking period"
                )
                preview["skipped_by_target_mismatch"].append(assessment_info)
                continue

            # Check if already exists
            existing = Assessment.objects.filter(
                gradebook=gradebook,
                name=template.name,
                marking_period=mp,
                assessment_type=template.assessment_type,
            ).first()

            if existing:
                assessment_info["existing_id"] = str(existing.id)
                preview["already_exists"].append(assessment_info)
            else:
                preview["will_create"].append(assessment_info)

    return preview


def get_grading_config(gradebook):
    """
    Get grading configuration from settings for a gradebook.

    Args:
        gradebook: GradeBook instance

    Returns:
        dict with grading configuration or None
    """
    try:
        if gradebook:
            try:
                from settings.models import GradingSettings
                
                # Get first grading settings (tenant-isolated by middleware)
                settings = GradingSettings.objects.first()
                if settings:
                    return {
                        "grading_style": settings.grading_style,
                        "grading_style_display": settings.get_grading_style_display(),
                        "single_entry_assessment_name": settings.single_entry_assessment_name,
                        "use_default_templates": settings.use_default_templates,
                        "auto_calculate_final_grade": settings.auto_calculate_final_grade,
                        "default_calculation_method": settings.default_calculation_method,
                        "require_grade_approval": settings.require_grade_approval,
                        "require_grade_review": settings.require_grade_review,
                        "display_assessment_on_single_entry": settings.display_assessment_on_single_entry,
                        "allow_assessment_delete": settings.allow_assessment_delete,
                        "allow_assessment_create": settings.allow_assessment_create,
                        "allow_assessment_edit": settings.allow_assessment_edit,
                        "use_letter_grades": settings.use_letter_grades,
                        "allow_teacher_override": settings.allow_teacher_override,
                        "lock_grades_after_semester": settings.lock_grades_after_semester,
                        "display_grade_status": settings.display_grade_status,
                        "cumulative_average_calculation": getattr(
                            settings, "cumulative_average_calculation", False
                        ),
                    }
            except (ProgrammingError, OperationalError):
                # Database schema doesn't match model (migration not adapted)
                # ProgrammingError for PostgreSQL, OperationalError for SQLite
                return None
        return None
    except AttributeError:
        return None


def get_grading_settings():
    """
    Get grading settings for current tenant.
    
    Returns:
        GradingSettings instance or None
    """
    try:
        from settings.models import GradingSettings
        
        # Get first grading settings (tenant-isolated by middleware)
        return GradingSettings.objects.first()
    except (ProgrammingError, OperationalError, Exception):
        return None


def get_workflow_settings():
    """
    Get workflow settings for grade status transitions.
    
    Returns:
        dict with require_grade_review and require_grade_approval, defaults to True
    """
    settings = get_grading_settings()
    if settings:
        return {
            "require_grade_review": settings.require_grade_review,
            "require_grade_approval": settings.require_grade_approval,
        }
    
    # Default to requiring both
    return {
        "require_grade_review": True,
        "require_grade_approval": True,
    }


def calculate_marking_period_percentage(
    gradebook, student, marking_period, status="any"
):
    """
    Calculate final percentage for a specific marking period.

    Args:
        gradebook: GradeBook instance
        student: Student instance
        marking_period: MarkingPeriod instance
        status: Grade status to filter by ('any' for all statuses, or specific status)
    """
    # Build the query
    query_filter = Q(
        assessment__gradebook=gradebook,
        assessment__marking_period=marking_period,
        student=student,
        assessment__is_calculated=True,
        score__isnull=False,
    )

    # Add status filter only if not 'any'
    if status != "any":
        query_filter &= Q(status=status)

    student_grades = Grade.objects.filter(query_filter).select_related("assessment")

    if not student_grades.exists():
        return None

    if gradebook.calculation_method == GradeBook.CalculationMethod.CUMULATIVE:
        total_earned = sum(Decimal(str(grade.score)) for grade in student_grades)
        total_possible = sum(
            Decimal(str(grade.assessment.max_score)) for grade in student_grades
        )
        if total_possible > 0:
            return (total_earned / total_possible * Decimal("100")).quantize(
                Decimal("0.01")
            )
        return None

    elif gradebook.calculation_method == GradeBook.CalculationMethod.WEIGHTED:
        total_weighted_score = Decimal("0")
        total_weight = Decimal("0")

        for grade in student_grades:
            if (
                grade.score is not None
                and grade.assessment.max_score
                and grade.assessment.weight
            ):
                percentage = (
                    Decimal(str(grade.score)) / Decimal(str(grade.assessment.max_score))
                ) * Decimal("100")
                weighted_score = percentage * Decimal(str(grade.assessment.weight))
                total_weighted_score += weighted_score
                total_weight += Decimal(str(grade.assessment.weight))

        if total_weight > 0:
            return (total_weighted_score / total_weight).quantize(Decimal("0.01"))
        return None

    else:  # Simple average
        total_percentage = Decimal("0")
        count = 0

        for grade in student_grades:
            if grade.score is not None and grade.assessment.max_score:
                percentage = (
                    Decimal(str(grade.score)) / Decimal(str(grade.assessment.max_score))
                ) * Decimal("100")
                total_percentage += percentage
                count += 1

        if count > 0:
            return (total_percentage / count).quantize(Decimal("0.01"))
        return None


def calculate_student_overall_average(
    student, academic_year, gradebooks=None, status="any"
):
    """
    Calculate a student's overall average across all gradebooks for an academic year.

    This uses the standardized grading calculation:
    1. For each gradebook, calculate final percentage for each marking period
    2. Aggregate by semester (average of all marking period grades in that semester)
    3. Calculate final average (average of all semester averages)

    Args:
        student: Student instance
        academic_year: AcademicYear instance
        gradebooks: Optional list of GradeBook instances. If None, gets all for student's enrollment
        status: Grade status to filter by ('any', 'approved', etc.)

    Returns:
        dict with:
        {
            'semester_averages': [
                {'id': semester_id, 'name': semester_name, 'average': float}
            ],
            'final_average': float,
            'total_gradebooks': int
        }
    """
    from academics.models import MarkingPeriod
    from collections import defaultdict

    # Get gradebooks if not provided
    if gradebooks is None:
        try:
            enrollment = Enrollment.objects.get(
                student=student, academic_year=academic_year
            )
            gradebooks = GradeBook.objects.filter(
                section=enrollment.section, academic_year=academic_year
            ).select_related("subject", "section", "section_subject")
        except Enrollment.DoesNotExist:
            return {"semester_averages": [], "final_average": None, "total_gradebooks": 0}

    if not gradebooks:
        return {"semester_averages": [], "final_average": None, "total_gradebooks": 0}

    # Get all marking periods for this academic year
    all_marking_periods = list(
        MarkingPeriod.objects.filter(semester__academic_year=academic_year, active=True)
        .select_related("semester")
        .order_by("semester__start_date", "start_date")
    )

    # Track grades across all gradebooks, aggregated by semester
    semester_totals = defaultdict(lambda: {"sum": 0, "count": 0})

    for gradebook in gradebooks:
        # Calculate per marking period
        for mp in all_marking_periods:
            # Calculate the final percentage for this marking period
            final_percentage = calculate_marking_period_percentage(
                gradebook, student, mp, status=status
            )

            if final_percentage is not None:
                # Aggregate by semester
                semester_totals[mp.semester.id]["sum"] += float(final_percentage)
                semester_totals[mp.semester.id]["count"] += 1

    # Calculate semester averages
    semester_averages = []
    total_sum = 0
    total_count = 0

    # Get unique semesters (maintain order)
    seen_semesters = set()
    for mp in all_marking_periods:
        if mp.semester.id not in seen_semesters:
            seen_semesters.add(mp.semester.id)
            semester_data = semester_totals.get(mp.semester.id)

            if semester_data and semester_data["count"] > 0:
                avg = semester_data["sum"] / semester_data["count"]
                semester_averages.append(
                    {
                        "id": str(mp.semester.id),
                        "name": mp.semester.name,
                        "average": round(avg, 1),
                    }
                )
                total_sum += avg
                total_count += 1

    final_average = round(total_sum / total_count, 1) if total_count > 0 else None

    return {
        "semester_averages": semester_averages,
        "final_average": final_average,
        "total_gradebooks": (
            len(list(gradebooks))
            if hasattr(gradebooks, "__iter__")
            else gradebooks.count()
        ),
    }

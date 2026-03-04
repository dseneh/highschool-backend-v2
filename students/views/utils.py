import uuid
import logging
from datetime import datetime

from academics.models import Section, Semester

logger = logging.getLogger(__name__)

def create_enrollment_for_student(
    student,
    academic_year,
    grade_level,
    section,
    request,
    status="pending",
    notes=None,
    date_enrolled=None,
    force=True,
    **kwargs
):
    if not grade_level.active:
        raise Exception(
            "Grade level is not active. Cannot enroll student in an inactive grade level."
        )

    if not section:
        c = grade_level.sections.filter(active=True).count()
        if c > 1:
            raise Exception(
                "Multiple sections found for this grade level, please specify a section"
            )
        elif c == 1:
            section = grade_level.sections.first()
        elif not section:
            section = Section.objects.create(
                id=uuid.uuid4(),
                grade_level=grade_level,
                name="General",
                updated_by=request.user,
                created_by=request.user,
            )

    re_enroll = request.data.get("re_enroll", False)
    current_enrollment = student.enrollments.filter(academic_year=academic_year)
    # Check if already enrolled
    if current_enrollment.exists():
        if re_enroll:
            # check if grades were already produced for this enrollment
            if not force:
                if (
                    current_enrollment.first()
                    .grades.filter(score__isnull=False)
                    .exists()
                ):
                    raise Exception(
                        "Cannot re-enroll student when grades have already been produced for this academic year"
                    )
            # delete the existing enrollment
            current_enrollment.delete()
            # Create a new enrollment
            enrollment = create_enrollment_for_student(
                student,
                academic_year,
                grade_level,
                section,
                request,
                status="pending",
                notes=None,
                date_enrolled=None,
                **kwargs
            )
            return enrollment

        raise Exception("Student is already enrolled in this academic year")

    enrolled_as = request.data.get("enrolled_as")
    if enrolled_as:
        if enrolled_as not in ["new", "returning", "transferred"]:
            raise Exception(
                "Invalid enrolled_as value. Must be 'new', 'returning', or 'transferred'"
            )
    else:
        # Auto-determine enrolled_as based on enrollment history
        # Check if student has any previous enrollments (excluding current academic year)
        has_previous_enrollment = student.enrollments.exclude(
            academic_year=academic_year
        ).exists()
        enrolled_as = "old" if has_previous_enrollment else "new"

    data = {
        "academic_year": academic_year,
        "grade_level": grade_level,
        "section": section,
        "status": status,
        "enrolled_as": enrolled_as,
        "date_enrolled": date_enrolled or datetime.now().today(),
        "notes": notes,
        "updated_by": request.user,
        "created_by": request.user,
    }

    enrollment = student.enrollments.create(**data)
    create_student_bill(enrollment, request)  # Create student bill

    # Create grade books
    subjects = section.section_subjects.filter(
        active=True
    )  # Get subjects from the specific section
    if not subjects:
        raise Exception(f"No subjects found for the selected class/section: {section.name}.")

    marking_periods = []
    for semester in Semester.objects.filter(active=True):
        marking_periods.extend(semester.marking_periods.filter(active=True))
    marking_periods = list(set(marking_periods))

    if not marking_periods:
        raise Exception("No marking periods found for this academic year")

    # Create grade entries for all assessments in the student's section
    create_grades_for_enrolled_student(enrollment, request.user)
    
    student.status = "enrolled"
    student.save()
    return enrollment

def create_grades_for_enrolled_student(enrollment, created_by):
    """
    Create grade entries for a newly enrolled student for all assessments
    in their section's gradebooks.
    
    Optimized for performance:
    - Single query to get all assessments
    - Bulk insert with batch_size=250
    - No unnecessary counts or checks
    - Uses only() to fetch minimal fields
    
    Args:
        enrollment: The student's enrollment record
        created_by: User creating the grades (typically the enrolling user)
    
    Returns:
        int: Number of grades created (or 0 if failed)
    """
    from grading.models import Grade, Assessment
    from django.db import transaction
    
    logger.info(f"Creating grades for enrolled student: {enrollment.student} in {enrollment.section}")
    
    # Single optimized query: Get all active assessments for this section/year
    # Use only() to fetch minimal required fields for performance
    assessments = Assessment.objects.filter(
        gradebook__section=enrollment.section,
        gradebook__academic_year=enrollment.academic_year,
        gradebook__active=True,
        active=True
    ).select_related(
        'gradebook__subject'
    ).only(
        'id',
        'gradebook__subject__id'
    )
    
    # Quick check: if no assessments, log warning and return
    assessments_list = list(assessments)  # Single query execution
    if not assessments_list or len(assessments_list) == 0:
        raise Exception(
            f"No assessments found for {enrollment.section} - {enrollment.academic_year}. "
            "Initialize gradebooks first."
        )
        return 0
    print(f"Found {len(assessments_list)} assessments for section {enrollment.section.name}, creating grades...")
    
    # Prepare grades for bulk creation
    # Skip duplicate check since enrollment is new (trust referential integrity)
    grades_to_create = [
        Grade(
            assessment=assessment,
            enrollment=enrollment,
            student=enrollment.student,
            academic_year=enrollment.academic_year,
            section=enrollment.section,
            subject=assessment.gradebook.subject,
            status=Grade.Status.DRAFT,
            score=None,
            comment=None,
            created_by=created_by,
            updated_by=created_by
        )
        for assessment in assessments_list
    ]
    print(f"Prepared {len(grades_to_create)} grade entries for bulk creation.")
    # Bulk create in single transaction
    try:
        with transaction.atomic():
            Grade.objects.bulk_create(grades_to_create, batch_size=250)
            grades_count = len(grades_to_create)
            logger.info(f"✓ Created {grades_count} grades for {enrollment.student}")
            print(f"✓ Successfully created {grades_count} grades for {enrollment.student}")
            return grades_count
    except Exception as e:
        print(f"Error creating grades for {enrollment.student}: {e}")
        logger.error(f"Failed to create grades for {enrollment.student}: {e}")
        return 0

def create_student_bill(enrollment, request):
    """Create student bills based on section fees and tuition fees."""

    all_section_fees = enrollment.section.section_fees.select_related(
        "general_fee"
    ).filter(active=True)
    section_fees = []

    for section_fee in all_section_fees:
        # Check if the fee applies to this student type or to all students (None)
        target_type = section_fee.general_fee.student_target
        if target_type == enrollment.enrolled_as:
            section_fees.append(section_fee)
        elif not target_type or target_type == "":
            section_fees.append(section_fee)

    bills = []

    # Create a bill for each section fee
    for section_fee in section_fees:
        bill = enrollment.student_bills.create(
            amount=section_fee.amount,
            created_by=request.user,
            updated_by=request.user,
            type="General",
            name=section_fee.general_fee.name,
            # date_created=timezone.now(),
        )

        bills.append(bill)

    # Create tuition bill - use section tuition_fee if set, otherwise grade level tuition_fee
    # tuition_amount = enrollment.section.tuition_fee
    # if tuition_amount is None or tuition_amount == 0:
    #     tuition_amount = enrollment.grade_level.tuition_fee

    tuition_fee = enrollment.grade_level.tuition_fees.filter(
        targeted_student_type=enrollment.enrolled_as
    ).first()

    if not tuition_fee or tuition_fee.amount is None or tuition_fee.amount == 0:
        raise Exception(
            f"No {enrollment.enrolled_as.upper()} student tuition fee found for this section or grade level, cannot enroll student."
        )

    tuition_amount = tuition_fee.amount

    if tuition_amount is None or tuition_amount == 0:
        raise Exception(
            "No tuition fee found for this section or grade level, cannot enroll student."
        )

    if tuition_amount and tuition_amount > 0:
        tuition_bill = enrollment.student_bills.create(
            name="Tuition",
            amount=tuition_amount,
            type="Tuition",
            created_by=request.user,
            updated_by=request.user,
        )
        bills.append(tuition_bill)

    return bills

# Import data from data folder
from .data.academic_year import get_academic_year
from .data.assessment_templates import assessment_templates_data
from .data.assessment_types import assessment_types_data
from .data.currency import currency
from .data.division_list import division_list
from .data.fees import fee_list
from .data.gade_level import grade_level_data
from .data.marking_period import get_marking_periods_dict
from .data.payment_methods import payment_method_data
from .data.semester import get_semester_list
from .data.subjects import subjects
from .data.transaction_types import transaction_types_data

# Note: Model imports moved inside functions to avoid circular import issues
# Models are imported when needed, not at module load time


def create_academic_year(tenant, user):
    """
    Create academic year in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from academics.models import AcademicYear
    
    academic_year_data = get_academic_year()
    with schema_context(tenant.schema_name):
        academic_year_obj = AcademicYear.objects.create(
            start_date=academic_year_data["start_date"],
            end_date=academic_year_data["end_date"],
            name=academic_year_data["name"],
            current=academic_year_data["current"],
            created_by=user,
            updated_by=user,
        )
    print("Created academic year...")
    return academic_year_obj


def create_semesters(academic_year, tenant, user):
    """
    Create semesters in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from academics.models import Semester
    
    semester_list_data = get_semester_list()
    semesters = []
    with schema_context(tenant.schema_name):
        for semester in semester_list_data:
            semester_obj = Semester.objects.create(
                academic_year=academic_year,
                name=semester["name"],
                start_date=semester["start_date"],
                end_date=semester["end_date"],
                created_by=user,
                updated_by=user,
            )
            semesters.append(semester_obj)
    print("Created semesters...")
    return semesters


def create_currency(tenant, user):
    """
    Create default currency in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from finance.models import Currency

    with schema_context(tenant.schema_name):
        Currency.objects.get_or_create(
            code=currency["code"],
            defaults={
                "name": currency["name"],
                "symbol": currency["symbol"],
                "created_by": user,
                "updated_by": user,
            },
        )
    print("Created default currency...")


def create_payment_methods(tenant, user):
    """
    Create default payment methods for financial transactions.
    """
    from django_tenants.utils import schema_context
    from finance.models import PaymentMethod

    with schema_context(tenant.schema_name):
        for method_data in payment_method_data:
            PaymentMethod.objects.get_or_create(
                name=method_data["name"],
                defaults={
                    "description": method_data["description"],
                    "is_editable": method_data.get("is_editable", True),
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created payment methods...")


def create_transaction_types(tenant, user):
    """
    Create default transaction types for financial transactions.
    """
    from django_tenants.utils import schema_context
    from finance.models import TransactionType

    with schema_context(tenant.schema_name):
        for i, trans_type in enumerate(transaction_types_data, start=1):
            TransactionType.objects.get_or_create(
                type_code=trans_type.get(
                    "type_code", trans_type.get("type_id", f"TRAN_TYPE_{i}")
                ),
                defaults={
                    "name": trans_type["name"],
                    "description": trans_type.get("description"),
                    "type": trans_type["type"],
                    "is_hidden": trans_type.get("is_hidden", False),
                    "is_editable": trans_type.get("is_editable", True),
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created transaction types...")


def create_fee_list(tenant, user):
    """
    Create default general fee list in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from finance.models import GeneralFeeList

    fee_objs = []
    with schema_context(tenant.schema_name):
        for fee in fee_list:
            fee_obj, _ = GeneralFeeList.objects.get_or_create(
                name=fee["name"],
                defaults={
                    "description": fee.get("description"),
                    "created_by": user,
                    "updated_by": user,
                },
            )
            fee_objs.append(fee_obj)
    print("Created fee list...")
    return fee_objs


def create_marking_periods(semesters, tenant, user):
    """
    Create marking periods in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from academics.models import MarkingPeriod
    
    marking_periods_data = get_marking_periods_dict()
    with schema_context(tenant.schema_name):
        for marking_period in marking_periods_data:
            # Get the appropriate semester object
            semester_obj = semesters[marking_period["semester"]]
            
            MarkingPeriod.objects.create(
                semester=semester_obj,
                name=marking_period["name"],
                short_name=marking_period["short_name"],
                start_date=marking_period["start_date"],
                end_date=marking_period["end_date"],
                created_by=user,
                updated_by=user,
            )
    print("Created marking periods...")


def create_divisions(tenant, user):
    """
    Create divisions in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from academics.models import Division
    
    divisions = []
    with schema_context(tenant.schema_name):
        for division in division_list:
            division_obj = Division.objects.create(
                name=division["name"],
                description=division["description"],
                created_by=user,
                updated_by=user,
            )
            divisions.append(division_obj)
    print("Created divisions...")
    return divisions


def create_grade_levels(tenant, divisions, user):
    """
    Create grade levels in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from academics.models import GradeLevel, GradeLevelTuitionFee
    
    grade_levels = []
    with schema_context(tenant.schema_name):
        for grade_level in grade_level_data:
            grade_level_obj = GradeLevel.objects.create(
                name=grade_level["name"],
                description=grade_level["description"],
                division=divisions[grade_level["division"]],
                level=grade_level["level"],
                short_name=grade_level["short_name"],
                created_by=user,
                updated_by=user,
            )
            grade_levels.append(grade_level_obj)
            # Create tuition fees for different student types
            typs = ["new", "returning", "transferred"]
            for t in typs:
                GradeLevelTuitionFee.objects.create(
                    grade_level=grade_level_obj,
                    targeted_student_type=t,
                    amount=0,
                    created_by=user,
                    updated_by=user,
                )
    print("Created grade levels...")
    return grade_levels


def create_sections(tenant, grade_levels, user):
    """
    Create sections in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from academics.models import Section
    
    sections = []
    with schema_context(tenant.schema_name):
        for grade_level in grade_levels:
            if grade_level.level <= 10:  # Up to Grade 10
                section_obj = Section.objects.create(
                    grade_level=grade_level,
                    name="General",
                    description=f"General Section for {grade_level.name}",
                    created_by=user,
                    updated_by=user,
                )
                sections.append(section_obj)
            elif grade_level.level <= 13:  # Grades 11-13
                section_obj = Section.objects.create(
                    grade_level=grade_level,
                    name="General",
                    description=f"General Section for {grade_level.name}",
                    created_by=user,
                    updated_by=user,
                )
                sections.append(section_obj)
            else:  # Grades 14+
                for section_name in ["Arts", "Science"]:
                    section_obj = Section.objects.create(
                        grade_level=grade_level,
                        name=section_name,
                        description=f"{section_name} Section for {grade_level.name}",
                        created_by=user,
                        updated_by=user,
                    )
                    sections.append(section_obj)
    print("Created sections...")
    return sections


def create_subjects(tenant, user):
    """
    Create subjects in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from academics.models import Subject
    
    subject_objs = []
    with schema_context(tenant.schema_name):
        for s in subjects:
            subject = Subject.objects.create(
                name=s["name"],
                description=s["description"],
                created_by=user,
                updated_by=user,
            )
            subject_objs.append(subject)
    print("Created subjects...")
    return subject_objs


def create_section_fees(tenant, sections, fee_list_objs, user):
    """
    Create section fees for each section based on general fee list.
    """
    from django_tenants.utils import schema_context
    from finance.models import SectionFee

    with schema_context(tenant.schema_name):
        for section in sections:
            for fee in fee_list_objs:
                SectionFee.objects.get_or_create(
                    section=section,
                    general_fee=fee,
                    defaults={
                        "amount": 0,
                        "created_by": user,
                        "updated_by": user,
                    },
                )
    print("Created section fees...")


def create_section_subjects(tenant, grade_levels, subjects, user):
    """
    Create section subjects in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from academics.models import SectionSubject
    
    with schema_context(tenant.schema_name):
        for grade_level in grade_levels:
            for section in grade_level.sections.all():
                for subject in subjects:
                    SectionSubject.objects.create(
                        section=section,
                        subject=subject,
                        created_by=user,
                        updated_by=user,
                    )
    print("Created section subjects...")


def create_periods(tenant, user):
    """
    Create periods in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from academics.models import Period
    
    period_list = [
        "Period 1",
        "Period 2",
        "Period 3",
        "Recess",
        "Period 4",
        "Period 5",
        "Period 6",
    ]
    periods = []
    with schema_context(tenant.schema_name):
        for p in period_list:
            period = Period.objects.create(
                name=p,
                description=f"School period: {p}",
                created_by=user,
                updated_by=user,
            )
            periods.append(period)
    print("Created periods...")
    return periods


def create_period_times(tenant, periods, user):
    """
    Create period times in the tenant's schema.
    """
    from django_tenants.utils import schema_context
    from academics.models import PeriodTime
    
    period_time_list = [
        {
            "start_time": "08:00:00",
            "end_time": "09:00:00",
            "day_of_week": 1,  # Monday
        },
        {
            "start_time": "09:00:00",
            "end_time": "10:00:00",
            "day_of_week": 1,
        },
        {
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "day_of_week": 1,
        },
        {
            "start_time": "11:00:00",
            "end_time": "12:00:00",
            "day_of_week": 1,
        },
        {
            "start_time": "12:00:00",
            "end_time": "13:00:00",
            "day_of_week": 1,
        },
        {
            "start_time": "13:00:00",
            "end_time": "14:00:00",
            "day_of_week": 1,
        },
        {
            "start_time": "14:00:00",
            "end_time": "15:00:00",
            "day_of_week": 1,
        },
    ]
    with schema_context(tenant.schema_name):
        for p in periods:
            for period_time_data in period_time_list:
                PeriodTime.objects.create(
                    period=p,
                    start_time=period_time_data["start_time"],
                    end_time=period_time_data["end_time"],
                    day_of_week=period_time_data["day_of_week"],
                    created_by=user,
                    updated_by=user,
                )
    print("Created period times...")


def create_grade_letters(tenant, user):
    """
    Create default grade letters for grading scale.
    """
    from django_tenants.utils import schema_context
    from grading.models import GradeLetter
    
    grade_letters_data = [
        {"letter": "A+", "min_percentage": 97, "max_percentage": 100, "order": 1},
        {"letter": "A", "min_percentage": 93, "max_percentage": 96, "order": 2},
        {"letter": "A-", "min_percentage": 90, "max_percentage": 92, "order": 3},
        {"letter": "B+", "min_percentage": 87, "max_percentage": 89, "order": 4},
        {"letter": "B", "min_percentage": 83, "max_percentage": 86, "order": 5},
        {"letter": "B-", "min_percentage": 80, "max_percentage": 82, "order": 6},
        {"letter": "C+", "min_percentage": 77, "max_percentage": 79, "order": 7},
        {"letter": "C", "min_percentage": 73, "max_percentage": 76, "order": 8},
        {"letter": "C-", "min_percentage": 70, "max_percentage": 72, "order": 9},
        {"letter": "D+", "min_percentage": 67, "max_percentage": 69, "order": 10},
        {"letter": "D", "min_percentage": 63, "max_percentage": 66, "order": 11},
        {"letter": "D-", "min_percentage": 60, "max_percentage": 62, "order": 12},
        {"letter": "F", "min_percentage": 0, "max_percentage": 59, "order": 13},
    ]
    
    with schema_context(tenant.schema_name):
        for grade_letter_data in grade_letters_data:
            GradeLetter.objects.get_or_create(
                letter=grade_letter_data["letter"],
                defaults={
                    "min_percentage": grade_letter_data["min_percentage"],
                    "max_percentage": grade_letter_data["max_percentage"],
                    "order": grade_letter_data["order"],
                    "created_by": user,
                    "updated_by": user,
                }
            )
    print("Created grade letters...")


def create_grade_settings(tenant, user):
    """
    Create default grade settings (placeholder for future enhancement).
    This can store school-wide grading policies.
    """
    from django_tenants.utils import schema_context
    
    with schema_context(tenant.schema_name):
        # TODO: Implement grade settings model if needed
        pass
    print("Grade settings configured...")


def create_departments(tenant, user):
    """
    Create default departments for staff organization.
    """
    from django_tenants.utils import schema_context
    from staff.models import Department
    
    departments_data = [
        {"name": "Academic", "code": "ACA"},
        {"name": "Administration", "code": "ADM"},
        {"name": "Support Services", "code": "SUP"},
    ]
    
    with schema_context(tenant.schema_name):
        for dept_data in departments_data:
            Department.objects.get_or_create(
                name=dept_data["name"],
                defaults={
                    "code": dept_data["code"],
                    "created_by": user,
                    "updated_by": user,
                }
            )
    print("Created departments...")


def create_position_categories(tenant, user):
    """
    Create default position categories for staff roles.
    """
    from django_tenants.utils import schema_context
    from staff.models import PositionCategory
    
    categories_data = [
        {"name": "Faculty", "description": "Teaching staff"},
        {"name": "Administrative", "description": "Administrative staff"},
        {"name": "Support", "description": "Support staff"},
    ]
    
    with schema_context(tenant.schema_name):
        for cat_data in categories_data:
            PositionCategory.objects.get_or_create(
                name=cat_data["name"],
                defaults={
                    "description": cat_data["description"],
                    "created_by": user,
                    "updated_by": user,
                }
            )
    print("Created position categories...")


def create_positions(tenant, user):
    """
    Create default positions for staff roles.
    """
    from django_tenants.utils import schema_context
    from staff.models import Department, PositionCategory, Position
    
    with schema_context(tenant.schema_name):
        # Get departments and categories
        academic_dept = Department.objects.filter(code="ACA").first()
        admin_dept = Department.objects.filter(code="ADM").first()
        faculty_cat = PositionCategory.objects.filter(name="Faculty").first()
        admin_cat = PositionCategory.objects.filter(name="Administrative").first()
        
        positions_data = [
            {
                "title": "Teacher",
                "code": "TCH",
                "category": faculty_cat,
                "department": academic_dept,
                "level": 1,
                "employment_type": "full_time",
                "compensation_type": "salary",
                "teaching_role": True,
            },
            {
                "title": "Principal",
                "code": "PRI",
                "category": admin_cat,
                "department": admin_dept,
                "level": 3,
                "employment_type": "full_time",
                "compensation_type": "salary",
                "teaching_role": False,
            },
            {
                "title": "Vice Principal",
                "code": "VPR",
                "category": admin_cat,
                "department": admin_dept,
                "level": 2,
                "employment_type": "full_time",
                "compensation_type": "salary",
                "teaching_role": False,
            },
            {
                "title": "Registrar",
                "code": "REG",
                "category": admin_cat,
                "department": admin_dept,
                "level": 2,
                "employment_type": "full_time",
                "compensation_type": "salary",
                "teaching_role": False,
            },
        ]
        
        for pos_data in positions_data:
            Position.objects.get_or_create(
                title=pos_data["title"],
                defaults={
                    "code": pos_data["code"],
                    "category": pos_data["category"],
                    "department": pos_data["department"],
                    "level": pos_data["level"],
                    "employment_type": pos_data["employment_type"],
                    "compensation_type": pos_data["compensation_type"],
                    "teaching_role": pos_data["teaching_role"],
                    "created_by": user,
                    "updated_by": user,
                }
            )
    print("Created positions...")


def create_assessment_types(tenant, user):
    """
    Create default assessment types for grading system.
    """
    from django_tenants.utils import schema_context
    from grading.models import AssessmentType
    
    with schema_context(tenant.schema_name):
        for assessment_type_data in assessment_types_data:
            AssessmentType.objects.get_or_create(
                name=assessment_type_data["name"],
                defaults={
                    "description": assessment_type_data["description"],
                    "is_single_entry": assessment_type_data["is_single_entry"],
                    "created_by": user,
                    "updated_by": user,
                }
            )
    print("Created assessment types...")


def create_assessment_templates(tenant, user):
    """
    Create default assessment templates for grading system.
    Templates are used to auto-generate assessments for gradebooks.
    """
    from django_tenants.utils import schema_context
    from grading.models import AssessmentType, DefaultAssessmentTemplate
    
    with schema_context(tenant.schema_name):
        for template_data in assessment_templates_data:
            # Get the assessment type by name
            assessment_type = AssessmentType.objects.filter(
                name=template_data["assessment_type_name"]
            ).first()
            
            if assessment_type:
                DefaultAssessmentTemplate.objects.get_or_create(
                    name=template_data["name"],
                    assessment_type=assessment_type,
                    defaults={
                        "max_score": template_data["max_score"],
                        "weight": template_data["weight"],
                        "is_calculated": template_data["is_calculated"],
                        "order": template_data["order"],
                        "description": template_data.get("description", ""),
                        "is_active": True,
                        "target": template_data["target"],
                        "created_by": user,
                        "updated_by": user,
                    }
                )
    print("Created assessment templates...")


def run_data_creation(tenant, user):
    """
    Create default tenant data after a tenant is created.
    This function should be called from tenant creation process.

    Args:
        tenant: Tenant instance that was just created
        user: User instance (usually the tenant admin/creator)
    """
    print(f"Creating default data for {tenant.name}...")
    
    # Academics initialization
    academic_year_obj = create_academic_year(tenant, user)
    semesters = create_semesters(academic_year_obj, tenant, user)

    # Finance defaults (replicate backend)
    create_currency(tenant, user)
    create_payment_methods(tenant, user)
    create_transaction_types(tenant, user)
    fee_list_objs = create_fee_list(tenant, user)

    create_marking_periods(semesters, tenant, user)
    divisions = create_divisions(tenant, user)
    grade_levels = create_grade_levels(tenant, divisions, user)
    sections = create_sections(tenant, grade_levels, user)
    create_section_fees(tenant, sections, fee_list_objs, user)
    subject_objs = create_subjects(tenant, user)
    # create_section_subjects(tenant, grade_levels, subject_objs, user)
    periods = create_periods(tenant, user)
    create_period_times(tenant, periods, user)

    # Grading initialization
    create_grade_letters(tenant, user)
    create_grade_settings(tenant, user)
    create_assessment_types(tenant, user)
    create_assessment_templates(tenant, user)

    # Staff initialization
    create_departments(tenant, user)
    create_position_categories(tenant, user)
    create_positions(tenant, user)
    
    print(f"Default data creation completed for {tenant.name}!")

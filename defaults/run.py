# Import data from data folder
from .data.academic_year import get_academic_year
from .data.accounting import (
    accounting_bank_accounts,
    accounting_currency,
    accounting_fee_items,
    accounting_ledger_accounts,
    accounting_payment_methods,
    accounting_transaction_types,
)
from .data.assessment_templates import assessment_templates_data
from .data.assessment_types import assessment_types_data
from .data.currency import currency
from .data.division_list import division_list
from .data.fees import fee_list
from .data.gade_level import grade_level_data
from .data.honor_categories import honor_categories
from .data.hr import employee_departments, employee_positions, leave_types
from .data.marking_period import get_marking_periods_dict
from .data.payment_methods import payment_method_data
from .data.payroll import get_default_pay_schedule
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
                code=s.get("code") or None,
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


def create_honor_categories(tenant, user):
    """Create default honor categories used by the dashboard honor distribution."""
    from django_tenants.utils import schema_context
    from grading.models import HonorCategory

    with schema_context(tenant.schema_name):
        for cat in honor_categories:
            HonorCategory.objects.get_or_create(
                label=cat["label"],
                defaults={
                    "min_average": cat["min_average"],
                    "max_average": cat["max_average"],
                    "color": cat.get("color", ""),
                    "icon": cat.get("icon", ""),
                    "order": cat.get("order", 0),
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created honor categories...")


def create_grading_settings(tenant, user):
    """Create the singleton GradingSettings row using model field defaults."""
    from django_tenants.utils import schema_context
    from settings.models import GradingSettings

    with schema_context(tenant.schema_name):
        if not GradingSettings.objects.exists():
            GradingSettings.objects.create(created_by=user, updated_by=user)
    print("Created grading settings...")


def create_school_calendar_settings(tenant, user):
    """Create the singleton SchoolCalendarSettings row (Mon–Fri operating days)."""
    from django_tenants.utils import schema_context
    from academics.models import SchoolCalendarSettings

    with schema_context(tenant.schema_name):
        if not SchoolCalendarSettings.objects.exists():
            SchoolCalendarSettings.objects.create(
                operating_days=[1, 2, 3, 4, 5],
                timezone="UTC",
                created_by=user,
                updated_by=user,
            )
    print("Created school calendar settings...")


def create_employee_departments(tenant, user):
    """Create default HR employee departments."""
    from django_tenants.utils import schema_context
    from hr.models import EmployeeDepartment

    with schema_context(tenant.schema_name):
        for dept in employee_departments:
            EmployeeDepartment.objects.get_or_create(
                name=dept["name"],
                defaults={
                    "code": dept.get("code", ""),
                    "description": dept.get("description"),
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created employee departments...")


def create_employee_positions(tenant, user):
    """Create default HR employee positions, linked to departments by code."""
    from django_tenants.utils import schema_context
    from hr.models import EmployeeDepartment, EmployeePosition

    with schema_context(tenant.schema_name):
        dept_by_code = {
            d.code: d for d in EmployeeDepartment.objects.exclude(code="")
        }
        for pos in employee_positions:
            department = dept_by_code.get(pos.get("department_code"))
            EmployeePosition.objects.get_or_create(
                title=pos["title"],
                department=department,
                defaults={
                    "code": pos.get("code", ""),
                    "description": pos.get("description"),
                    "employment_type": pos.get("employment_type", "full_time"),
                    "can_teach": pos.get("can_teach", False),
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created employee positions...")


def create_leave_types(tenant, user):
    """Create default HR leave types."""
    from django_tenants.utils import schema_context
    from hr.models import LeaveType

    with schema_context(tenant.schema_name):
        for lt in leave_types:
            LeaveType.objects.get_or_create(
                name=lt["name"],
                defaults={
                    "code": lt.get("code", ""),
                    "description": lt.get("description"),
                    "default_days": lt.get("default_days", 1),
                    "requires_approval": lt.get("requires_approval", True),
                    "accrual_frequency": lt.get("accrual_frequency", "upfront"),
                    "allow_carryover": lt.get("allow_carryover", False),
                    "max_carryover_days": lt.get("max_carryover_days", 0),
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created leave types...")


def create_accounting_currency(tenant, user):
    """Create the tenant's base AccountingCurrency."""
    from django_tenants.utils import schema_context
    from accounting.models import AccountingCurrency

    with schema_context(tenant.schema_name):
        obj, _ = AccountingCurrency.objects.get_or_create(
            code=accounting_currency["code"],
            defaults={
                "name": accounting_currency["name"],
                "symbol": accounting_currency["symbol"],
                "is_base_currency": accounting_currency.get("is_base_currency", True),
                "decimal_places": accounting_currency.get("decimal_places", 2),
                "is_active": True,
                "created_by": user,
                "updated_by": user,
            },
        )
    print("Created accounting currency...")
    return obj


def create_accounting_ledger_accounts(tenant, user):
    """Create the default chart of accounts.

    Two-pass create: parents/headers first, then children with their
    `parent_account` FK resolved by `parent_code`.
    """
    from django_tenants.utils import schema_context
    from accounting.models import AccountingLedgerAccount

    parents = [a for a in accounting_ledger_accounts if not a.get("parent_code")]
    children = [a for a in accounting_ledger_accounts if a.get("parent_code")]

    with schema_context(tenant.schema_name):
        for acct in parents + children:
            parent_obj = None
            if acct.get("parent_code"):
                parent_obj = AccountingLedgerAccount.objects.filter(
                    code=acct["parent_code"]
                ).first()

            AccountingLedgerAccount.objects.get_or_create(
                code=acct["code"],
                defaults={
                    "name": acct["name"],
                    "account_type": acct["account_type"],
                    "category": acct.get("category", ""),
                    "normal_balance": acct["normal_balance"],
                    "is_active": True,
                    "is_header": acct.get("is_header", False),
                    "is_system_managed": acct.get("is_system_managed", False),
                    "parent_account": parent_obj,
                    "description": acct.get("description"),
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created accounting ledger accounts...")


def create_accounting_payment_methods(tenant, user):
    """Create default accounting payment methods."""
    from django_tenants.utils import schema_context
    from accounting.models import AccountingPaymentMethod

    with schema_context(tenant.schema_name):
        for pm in accounting_payment_methods:
            AccountingPaymentMethod.objects.get_or_create(
                code=pm["code"],
                defaults={
                    "name": pm["name"],
                    "description": pm.get("description"),
                    "is_active": True,
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created accounting payment methods...")


def create_accounting_transaction_types(tenant, user):
    """Create default accounting transaction types.

    Resolves `default_ledger_account_code` to the seeded chart-of-accounts entry
    so income/expense/transfer postings auto-route to the correct GL account.
    """
    from django_tenants.utils import schema_context
    from accounting.models import AccountingLedgerAccount, AccountingTransactionType

    with schema_context(tenant.schema_name):
        for tt in accounting_transaction_types:
            ledger_account = (
                AccountingLedgerAccount.objects.filter(code=tt.get("default_ledger_account_code")).first()
                if tt.get("default_ledger_account_code")
                else None
            )
            AccountingTransactionType.objects.get_or_create(
                code=tt["code"],
                defaults={
                    "name": tt["name"],
                    "transaction_category": tt["transaction_category"],
                    "description": tt.get("description"),
                    "default_ledger_account": ledger_account,
                    "is_system_managed": tt.get("is_system_managed", False),
                    "is_active": True,
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created accounting transaction types...")


def create_accounting_fee_items(tenant, user):
    """Create default accounting fee item catalog."""
    from django_tenants.utils import schema_context
    from accounting.models import AccountingFeeItem

    with schema_context(tenant.schema_name):
        for fi in accounting_fee_items:
            AccountingFeeItem.objects.get_or_create(
                code=fi["code"],
                defaults={
                    "name": fi["name"],
                    "category": fi["category"],
                    "description": fi.get("description"),
                    "is_active": True,
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created accounting fee items...")


def create_accounting_bank_accounts(tenant, user, accounting_currency_obj):
    """Create the default in-house savings bank account.

    Linked to the matching ledger account (e.g. 1100 Bank) by code so postings
    auto-resolve to a balance-sheet bank account.
    """
    from django_tenants.utils import schema_context
    from accounting.models import AccountingBankAccount, AccountingLedgerAccount

    if accounting_currency_obj is None:
        print("Skipped bank accounts (no accounting currency)...")
        return

    with schema_context(tenant.schema_name):
        for ba in accounting_bank_accounts:
            ledger_account = (
                AccountingLedgerAccount.objects.filter(code=ba.get("ledger_account_code")).first()
                if ba.get("ledger_account_code")
                else None
            )
            AccountingBankAccount.objects.get_or_create(
                account_number=ba["account_number"],
                defaults={
                    "account_name": ba["account_name"],
                    "bank_name": ba.get("bank_name", ""),
                    "account_type": ba["account_type"],
                    "currency": accounting_currency_obj,
                    "ledger_account": ledger_account,
                    "opening_balance": ba.get("opening_balance", 0),
                    "status": ba.get("status", "active"),
                    "description": ba.get("description"),
                    "created_by": user,
                    "updated_by": user,
                },
            )
    print("Created accounting bank accounts...")


def create_default_pay_schedule(tenant, user, accounting_currency_obj):
    """Create the default monthly PaySchedule for the tenant."""
    from django_tenants.utils import schema_context
    from payroll.models import PaySchedule

    if accounting_currency_obj is None:
        print("Skipped pay schedule (no accounting currency)...")
        return None

    data = get_default_pay_schedule()
    with schema_context(tenant.schema_name):
        obj, _ = PaySchedule.objects.get_or_create(
            name=data["name"],
            defaults={
                "frequency": data["frequency"],
                "anchor_date": data["anchor_date"],
                "currency": accounting_currency_obj,
                "payment_day_offset": data["payment_day_offset"],
                "overtime_multiplier": data["overtime_multiplier"],
                "is_default": data["is_default"],
                "is_active": data["is_active"],
                "created_by": user,
                "updated_by": user,
            },
        )
    print("Created default pay schedule...")
    return obj


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

    # Calendar
    create_school_calendar_settings(tenant, user)

    # Grading initialization
    create_grade_letters(tenant, user)
    create_grade_settings(tenant, user)
    create_grading_settings(tenant, user)
    create_assessment_types(tenant, user)
    create_assessment_templates(tenant, user)
    create_honor_categories(tenant, user)

    # Staff initialization (legacy staff app)
    create_departments(tenant, user)
    create_position_categories(tenant, user)
    create_positions(tenant, user)

    # HR initialization (employee-first)
    create_employee_departments(tenant, user)
    create_employee_positions(tenant, user)
    create_leave_types(tenant, user)

    # Accounting initialization (chart of accounts + lookups)
    accounting_currency_obj = create_accounting_currency(tenant, user)
    create_accounting_ledger_accounts(tenant, user)
    create_accounting_payment_methods(tenant, user)
    create_accounting_transaction_types(tenant, user)
    create_accounting_fee_items(tenant, user)
    create_accounting_bank_accounts(tenant, user, accounting_currency_obj)

    # Payroll initialization (depends on accounting currency)
    create_default_pay_schedule(tenant, user, accounting_currency_obj)
    
    print(f"Default data creation completed for {tenant.name}!")

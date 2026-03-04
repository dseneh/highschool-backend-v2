from faker import Faker

from core.models import School
from finance.models import TransactionType
from students.models import Student
from users.models import CustomUser

fake = Faker()


def create_superuser():
    user = CustomUser.objects.create_superuser(
        id_number="admin01",
        email="dew@gmail.com",
        username="admin",
        password="0000",
        is_superuser=True,
        is_staff=True,
        gender="male",
    )
    print("Created superuser...")
    return user


def create_school(user):
    school = School.objects.create(
        id_number="0001",
        name="Dujar High School",
        short_name="DHS",
        school_type="public",
        description=fake.catch_phrase(),
        address=fake.street_address(),
        city=fake.city(),
        state=fake.state(),
        country="United States",
        postal_code=fake.postcode(),
        phone=fake.phone_number(),
        email=fake.email(),
        workspace="dujar",
        date_est=fake.date(),
        school_motto=fake.catch_phrase(),
        website=fake.url(),
        logo="images/logo.png",
        created_by=user,
        updated_by=user,
    )
    print("Created default school...")
    return school


def create_academic_year(school, user):
    academic_year = school.academic_years.create(
        start_date="2025-01-01",
        end_date="2025-12-31",
        name="Demo 2025",
        current=True,
        created_by=user,
        updated_by=user,
    )
    print("Created academic year...")
    return academic_year


def create_semesters(school, user):
    semester_list = [
        {
            "name": "Semester 1",
            "start_date": "2025-01-01",
            "end_date": "2025-06-30",
        },
        {
            "name": "Semester 2",
            "start_date": "2025-07-01",
            "end_date": "2025-12-31",
        },
    ]
    semesters = []
    for semester in semester_list:
        semester_obj = school.semesters.create(
            name=semester["name"],
            start_date=semester["start_date"],
            end_date=semester["end_date"],
            created_by=user,
            updated_by=user,
        )
        semesters.append(semester_obj)
        print(f'Created semester {semester["name"]}...')
    return semesters


def create_currency(school, user):
    currency = school.currencies.create(
        name="Liberian Dollar",
        code="LRD",
        symbol="$",
        created_by=user,
        updated_by=user,
    )
    print("Created default currency...")
    return currency


def create_transaction_types(user, school):
    trans_types = [
        {
            "name": "School Fees Payment",
            "description": "Fees paid for tuition",
            "type": "income",
            "type_id": "TUITION",
            "is_hidden": False,
            "is_editable": False,
        },
        {
            "name": "Transfer Out",
            "description": "Transfer money to another account",
            "type": "expense",
            "type_id": "TRANSFER_OUT",
            "is_hidden": True,
            "is_editable": False,
        },
        {
            "name": "Transfer In",
            "description": "Transfer money from another account",
            "type": "income",
            "type_id": "TRANSFER_IN",
            "is_hidden": True,
            "is_editable": False,
        },
        {
            "name": "Refund Payment",
            "description": "Refund for overpayment or cancellation",
            "type": "expense",
            "type_id": "REFUND",
            "is_hidden": False,
            "is_editable": False,
        },
        {
            "name": "Donation",
            "description": "Donations made to the school",
            "type": "income",
        },
        {
            "name": "Item Purchase",
            "description": "Purchase of school items",
            "type": "expense",
        },
        {
            "name": "Facility Maintenance",
            "description": "School facility maintenance expenses",
            "type": "expense",
        },
        {
            "name": "Staff Salary",
            "description": "Staff salary payments",
            "type": "expense",
        },
        {
            "name": "Utility Payment",
            "description": "Utility bills payment",
            "type": "expense",
        },
        {
            "name": "Other Income",
            "description": "Other types of income transactions",
            "type": "income",
        },
        {
            "name": "Other Expense",
            "description": "Other types of expense transactions",
            "type": "expense",
        },
    ]

    for i, trans_type in enumerate(trans_types, start=1):
        school.transaction_types.create(
            name=trans_type["name"],
            description=trans_type["description"],
            type_code=trans_type.get("type_id", f"TRAN_TYPE_{i}"),
            is_hidden=trans_type.get("is_hidden", False),
            is_editable=trans_type.get("is_editable", True),
            type=trans_type["type"],
            created_by=user,
            updated_by=user,
        )
    print("Created transaction types...")


def create_fee_list(school, user):
    fee_list = [
        {
            "name": "Registration Fee",
            "description": "Fee for registering a new student",
        },
        {
            "name": "Library Fee",
            "description": "Fee for using the school library",
        },
        {
            "name": "Lab Fee",
            "description": "Fee for using science or computer labs",
        },
        {
            "name": "Sports Fee",
            "description": "Fee for participating in sports activities",
        },
        {
            "name": "Activity Fee",
            "description": "Fee for extracurricular activities",
        },
        {
            "name": "Graduation Fee",
            "description": "Fee for graduation ceremony and materials",
        },
        {
            "name": "Uniform Fee",
            "description": "Fee for school uniforms",
        },
        {
            "name": "Transportation Fee",
            "description": "Fee for school transportation services",
        },
        {
            "name": "Technology Fee",
            "description": "Fee for using school technology resources",
        },
    ]
    lst = []
    for fee in fee_list:
        fee_obj = school.general_fees.create(
            name=fee["name"],
            description=fee["description"],
            created_by=user,
            updated_by=user,
        )
        lst.append(fee_obj)
    print("Created fee list...")
    return lst


def create_marking_periods(semesters, user):
    marking_periods_dict = [
        {
            "name": "Marking Period 1",
            "short_name": "Pd 1",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "semester": semesters[0],
        },
        {
            "name": "Marking Period 2",
            "short_name": "Pd 2",
            "start_date": "2025-02-01",
            "end_date": "2025-02-28",
            "semester": semesters[0],
        },
        {
            "name": "Marking Period 3",
            "short_name": "Pd 3",
            "start_date": "2025-03-01",
            "end_date": "2025-03-31",
            "semester": semesters[0],
        },
        {
            "name": "Semester 1 Exam",
            "short_name": "Sem Exam 1",
            "start_date": "2025-04-01",
            "end_date": "2025-04-07",
            "semester": semesters[0],
        },
        {
            "name": "Marking Period 4",
            "short_name": "Pd 4",
            "start_date": "2025-04-08",
            "end_date": "2025-04-30",
            "semester": semesters[1],
        },
        {
            "name": "Marking Period 5",
            "short_name": "Pd 5",
            "start_date": "2025-05-01",
            "end_date": "2025-05-31",
            "semester": semesters[1],
        },
        {
            "name": "Marking Period 6",
            "short_name": "Pd 6",
            "start_date": "2025-06-01",
            "end_date": "2025-06-30",
            "semester": semesters[1],
        },
        {
            "name": "Semester 2 Exam",
            "short_name": "Sem Exam 2",
            "start_date": "2025-07-01",
            "end_date": "2025-07-07",
            "semester": semesters[1],
        },
    ]

    for marking_period in marking_periods_dict:
        marking_period["semester"].marking_periods.create(
            name=marking_period["name"],
            short_name=marking_period["short_name"],
            start_date=marking_period["start_date"],
            end_date=marking_period["end_date"],
            created_by=user,
            updated_by=user,
        )
        print(f'Created marking period {marking_period["name"]}...')
    print("Created marking periods...")


def create_divisions(school, user):
    division_list = [
        "Preschool",
        "Elementary",
        "Junior High School",
        "Senior High School",
    ]
    divisions = []
    for division in division_list:
        division_obj = school.divisions.create(
            name=division,
            description=fake.catch_phrase(),
            created_by=user,
            updated_by=user,
        )
        divisions.append(division_obj)
        print(f"Created division {division}...")
    print("Created divisions...")
    return divisions


def create_grade_levels(school, divisions, user):
    grade_level_list = [
        {
            "name": "Nursery 1",
            "description": fake.catch_phrase(),
            "division": divisions[0],
            "level": 1,
            "short_name": "N1",
        },
        {
            "name": "Nursery 2",
            "description": fake.catch_phrase(),
            "division": divisions[0],
            "level": 2,
            "short_name": "N2",
        },
        {
            "name": "Kindergarten 1",
            "description": fake.catch_phrase(),
            "division": divisions[1],
            "level": 3,
            "short_name": "KG1",
        },
        {
            "name": "Kindergarten 2",
            "description": fake.catch_phrase(),
            "division": divisions[1],
            "level": 4,
            "short_name": "KG2",
        },
        {
            "name": "Grade 1",
            "description": fake.catch_phrase(),
            "division": divisions[1],
            "level": 5,
            "short_name": "G1",
        },
        {
            "name": "Grade 2",
            "description": fake.catch_phrase(),
            "division": divisions[1],
            "level": 6,
            "short_name": "G2",
        },
        {
            "name": "Grade 3",
            "description": fake.catch_phrase(),
            "division": divisions[1],
            "level": 7,
            "short_name": "G3",
        },
        {
            "name": "Grade 4",
            "description": fake.catch_phrase(),
            "division": divisions[1],
            "level": 8,
            "short_name": "G4",
        },
        {
            "name": "Grade 5",
            "description": fake.catch_phrase(),
            "division": divisions[1],
            "level": 9,
            "short_name": "G5",
        },
        {
            "name": "Grade 6",
            "description": fake.catch_phrase(),
            "division": divisions[1],
            "level": 10,
            "short_name": "G6",
        },
        {
            "name": "Grade 7",
            "description": fake.catch_phrase(),
            "division": divisions[2],
            "level": 11,
            "short_name": "G7",
        },
        {
            "name": "Grade 8",
            "description": fake.catch_phrase(),
            "division": divisions[2],
            "level": 12,
            "short_name": "G8",
        },
        {
            "name": "Grade 9",
            "description": fake.catch_phrase(),
            "division": divisions[2],
            "level": 13,
            "short_name": "G9",
        },
        {
            "name": "Grade 10",
            "description": fake.catch_phrase(),
            "division": divisions[3],
            "level": 14,
            "short_name": "G10",
        },
        {
            "name": "Grade 11",
            "description": fake.catch_phrase(),
            "division": divisions[3],
            "level": 15,
            "short_name": "G11",
        },
        {
            "name": "Grade 12",
            "description": fake.catch_phrase(),
            "division": divisions[3],
            "level": 16,
            "short_name": "G12",
        },
    ]

    grade_levels = []
    for grade_level in grade_level_list:
        grade_level_obj = school.grade_levels.create(
            name=grade_level["name"],
            description=grade_level["description"],
            division=grade_level["division"],
            level=grade_level["level"],
            short_name=grade_level["short_name"],
            # tuition_fee=fake.random_int(min=3000, max=10000),
            created_by=user,
            updated_by=user,
        )
        grade_levels.append(grade_level_obj)
        print(f'Created grade level {grade_level["name"]}...')
        typs = ["new", "returning", "transferred"]
        for t in typs:
            grade_level_obj.tuition_fees.create(
                targeted_student_type=t,
                amount=0,
                created_by=user,
                updated_by=user,
            )
    print("Created grade levels...")
    return grade_levels


def create_sections(grade_levels, user):
    section_list = [
        {
            "name": "General",
            "description": "General Section for Grade 1",
            "grade_level": grade_levels[0],
        },
        {
            "name": "General",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[1],
        },
        {
            "name": "General",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[2],
        },
        {
            "name": "General",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[3],
        },
        {
            "name": "General",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[4],
        },
        {
            "name": "General",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[5],
        },
        {
            "name": "General",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[6],
        },
        {
            "name": "General",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[7],
        },
        {
            "name": "General",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[8],
        },
        {
            "name": "Arts A",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[9],
        },
        {
            "name": "Arts B",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[9],
        },
        {
            "name": "Science A",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[9],
        },
        {
            "name": "Science B",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[9],
        },
        {
            "name": "Arts",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[10],
        },
        {
            "name": "Science",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[10],
        },
        {
            "name": "Arts",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[11],
        },
        {
            "name": "Science",
            "description": fake.catch_phrase(),
            "grade_level": grade_levels[11],
        },
    ]
    sections = []
    for section in section_list:
        section_obj = section["grade_level"].sections.create(
            name=section["name"],
            description=section["description"],
            created_by=user,
            updated_by=user,
        )
        sections.append(section_obj)
        print(f'Created section {section["name"]}...')
    print("Created sections...")
    return sections


def create_section_fees(sections, fee_list, user):
    for section in sections:
        for fee in fee_list:
            section.section_fees.create(
                general_fee=fee,
                amount=fake.random_int(min=100, max=500),
                created_by=user,
                updated_by=user,
            )
            print(f"Created section fee for {section.name}...")
    print("Created section fees...")


def create_subjects(school, user):
    subject_name = [
        "Mathematics",
        "English",
        "Science",
        "History",
        "Geography",
        "Physical Education",
        "Art",
        "Music",
        "Computer Science",
        "Health",
        "Social Studies",
        "Biology",
        "Chemistry",
        "Physics",
    ]
    subjects = []
    for s in subject_name:
        subject = school.subjects.create(
            name=s,
            description=fake.catch_phrase(),
            created_by=user,
            updated_by=user,
        )
        subjects.append(subject)
        print(f"Created subject {s}...")
    print("Created subjects...")
    return subjects


def create_section_subjects(grade_levels, subjects, user):
    for grade_level in grade_levels:
        for c in grade_level.sections.all():
            for subject in subjects:
                c.section_subjects.create(
                    subject=subject,
                    created_by=user,
                    updated_by=user,
                )
                print(f"Created class room subject for {c.name}...")
    print("Created section subjects...")


def create_periods(school, user):
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
    for p in period_list:
        period = school.periods.create(
            name=p,
            description=fake.catch_phrase(),
            created_by=user,
            updated_by=user,
        )
        periods.append(period)
        print(f"Created period {p}...")
    print("Created periods...")
    return periods


def create_period_times(periods, user):
    period_time_list = [
        {
            "start_time": "08:00:00",
            "end_time": "09:00:00",
            "day_of_week": 0,
            "period": periods[0],
        },
        {
            "start_time": "09:00:00",
            "end_time": "10:00:00",
            "day_of_week": 0,
            "period": periods[1],
        },
        {
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "day_of_week": 0,
            "period": periods[2],
        },
        {
            "start_time": "11:00:00",
            "end_time": "12:00:00",
            "day_of_week": 0,
            "period": periods[3],
        },
        {
            "start_time": "12:00:00",
            "end_time": "13:00:00",
            "day_of_week": 0,
            "period": periods[4],
        },
        {
            "start_time": "13:00:00",
            "end_time": "14:00:00",
            "day_of_week": 0,
            "period": periods[5],
        },
        {
            "start_time": "14:00:00",
            "end_time": "15:00:00",
            "day_of_week": 0,
            "period": periods[6],
        },
    ]
    for p in periods:
        for period_time in period_time_list:
            period_time["period"] = p
            period_time_obj = p.period_times.create(
                start_time=period_time["start_time"],
                end_time=period_time["end_time"],
                day_of_week=period_time["day_of_week"],
                period=period_time["period"],
                created_by=user,
                updated_by=user,
            )
            print(f"Created period time {period_time_obj}...")
    print("Created period times...")


def create_students(school, grade_levels, user):
    for i in range(10):
        gender = fake.random_element(elements=["male", "female"])

        # Use proper sequence allocation to prevent UNIQUE constraint violations
        from students.models import Student

        student_seq = Student.allocate_next_seq(school)
        school_code = int(school.id_number[-2:]) if school.id_number else 1

        student = school.students.create(
            # Don't set id_number manually - let the model compute it from school_code + student_seq
            school_code=school_code,
            student_seq=student_seq,
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            date_of_birth=fake.date_of_birth(minimum_age=5, maximum_age=18),
            gender=gender,
            email=fake.email(),
            phone_number=fake.phone_number(),
            address=fake.street_address(),
            city=fake.city(),
            state=fake.state(),
            postal_code=fake.zipcode(),
            country=fake.country(),
            status=fake.random_element(elements=["active", "inactive"]),
            entry_date=fake.date(),
            date_of_graduation=fake.date(),
            place_of_birth=fake.city(),
            grade_level=fake.random_element(elements=grade_levels),
            prev_id_number=fake.random_int(min=1, max=1000),
            entry_as="new",  # Add required field
            created_by=user,
            updated_by=user,
            school=school,
        )

        user_account = CustomUser.objects.create(
            id_number=student.id_number,
            email=student.email,
            username=student.id_number,
            password=student.id_number,
            role="student",
            school=school,
            gender=student.gender,
        )
        student.user_account = user_account
        student.save()
        print(
            f"Created student {student.first_name} {student.last_name} :: {student.id_number}..."
        )
    print("Created dummy students...")


def run_data_creation():
    print("Creating dummy data...")
    user = create_superuser()
    school = create_school(user)
    academic_year = create_academic_year(school, user)
    semesters = create_semesters(school, user)
    create_currency(school, user)
    create_transaction_types(user, school)
    fee_list = create_fee_list(school, user)
    create_marking_periods(semesters, user)
    divisions = create_divisions(school, user)
    grade_levels = create_grade_levels(school, divisions, user)
    sections = create_sections(grade_levels, user)
    create_section_fees(sections, fee_list, user)
    subjects = create_subjects(school, user)
    create_section_subjects(grade_levels, subjects, user)
    periods = create_periods(school, user)
    create_period_times(periods, user)
    # create_students(school, grade_levels, user)

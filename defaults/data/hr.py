"""Default seed data for the `hr` module.

Seeded at tenant creation so each new tenant has baseline employee
departments, positions and leave types ready for use.
"""

employee_departments = [
    {"name": "Academic", "code": "ACA", "description": "Teaching and academic staff"},
    {"name": "Administration", "code": "ADM", "description": "Administrative staff"},
    {"name": "Support Services", "code": "SUP", "description": "Support staff (maintenance, IT, etc.)"},
    {"name": "Finance", "code": "FIN", "description": "Finance and accounting staff"},
    {"name": "Human Resources", "code": "HR", "description": "Human resources staff"},
]


# `department_code` is resolved at seed time to the matching EmployeeDepartment.
employee_positions = [
    {
        "title": "Teacher",
        "code": "TCH",
        "department_code": "ACA",
        "employment_type": "full_time",
        "can_teach": True,
        "description": "Classroom teacher",
    },
    {
        "title": "Department Head",
        "code": "DHD",
        "department_code": "ACA",
        "employment_type": "full_time",
        "can_teach": True,
        "description": "Head of academic department",
    },
    {
        "title": "Principal",
        "code": "PRI",
        "department_code": "ADM",
        "employment_type": "full_time",
        "can_teach": False,
        "description": "School principal",
    },
    {
        "title": "Vice Principal",
        "code": "VPR",
        "department_code": "ADM",
        "employment_type": "full_time",
        "can_teach": False,
        "description": "Vice / assistant principal",
    },
    {
        "title": "Registrar",
        "code": "REG",
        "department_code": "ADM",
        "employment_type": "full_time",
        "can_teach": False,
        "description": "Registrar",
    },
    {
        "title": "Accountant",
        "code": "ACC",
        "department_code": "FIN",
        "employment_type": "full_time",
        "can_teach": False,
        "description": "Accountant",
    },
    {
        "title": "HR Officer",
        "code": "HRO",
        "department_code": "HR",
        "employment_type": "full_time",
        "can_teach": False,
        "description": "HR officer",
    },
    {
        "title": "Janitor",
        "code": "JAN",
        "department_code": "SUP",
        "employment_type": "full_time",
        "can_teach": False,
        "description": "Janitorial staff",
    },
    {
        "title": "Security Officer",
        "code": "SEC",
        "department_code": "SUP",
        "employment_type": "full_time",
        "can_teach": False,
        "description": "Security staff",
    },
]


leave_types = [
    {
        "name": "Annual Leave",
        "code": "ANNUAL",
        "default_days": 15,
        "requires_approval": True,
        "accrual_frequency": "annually",
        "allow_carryover": True,
        "max_carryover_days": 5,
        "description": "Paid annual / vacation leave",
    },
    {
        "name": "Sick Leave",
        "code": "SICK",
        "default_days": 10,
        "requires_approval": True,
        "accrual_frequency": "annually",
        "allow_carryover": False,
        "max_carryover_days": 0,
        "description": "Paid sick leave",
    },
    {
        "name": "Personal Leave",
        "code": "PERSONAL",
        "default_days": 3,
        "requires_approval": True,
        "accrual_frequency": "annually",
        "allow_carryover": False,
        "max_carryover_days": 0,
        "description": "Personal / casual leave",
    },
    {
        "name": "Maternity Leave",
        "code": "MATERNITY",
        "default_days": 90,
        "requires_approval": True,
        "accrual_frequency": "upfront",
        "allow_carryover": False,
        "max_carryover_days": 0,
        "description": "Maternity leave",
    },
    {
        "name": "Paternity Leave",
        "code": "PATERNITY",
        "default_days": 14,
        "requires_approval": True,
        "accrual_frequency": "upfront",
        "allow_carryover": False,
        "max_carryover_days": 0,
        "description": "Paternity leave",
    },
    {
        "name": "Bereavement Leave",
        "code": "BEREAVEMENT",
        "default_days": 5,
        "requires_approval": True,
        "accrual_frequency": "upfront",
        "allow_carryover": False,
        "max_carryover_days": 0,
        "description": "Bereavement leave",
    },
    {
        "name": "Unpaid Leave",
        "code": "UNPAID",
        "default_days": 0,
        "requires_approval": True,
        "accrual_frequency": "upfront",
        "allow_carryover": False,
        "max_carryover_days": 0,
        "description": "Unpaid leave of absence",
    },
]

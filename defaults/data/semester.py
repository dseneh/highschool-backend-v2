from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta


def get_semester_list():
    """
    Generate semester data with equal 6-month periods within the academic year.
    """
    today = datetime.now().date()
    academic_start = today.replace(day=1)  # First of current month

    # First semester: 6 months
    semester1_start = academic_start
    semester1_end = academic_start + relativedelta(months=6) - timedelta(days=1)

    # Second semester: next 6 months
    semester2_start = academic_start + relativedelta(months=6)
    semester2_end = academic_start + relativedelta(months=12) - timedelta(days=1)

    return [
        {
            "name": "First Semester",
            "start_date": semester1_start.strftime("%Y-%m-%d"),
            "end_date": semester1_end.strftime("%Y-%m-%d"),
            "status": "active",
        },
        {
            "name": "Second Semester",
            "start_date": semester2_start.strftime("%Y-%m-%d"),
            "end_date": semester2_end.strftime("%Y-%m-%d"),
            "status": "active",
        },
    ]


# For backward compatibility
semester_list = get_semester_list()

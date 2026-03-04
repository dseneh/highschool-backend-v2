from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta


def get_marking_periods_dict():
    """
    Generate marking periods data with 6 equally distributed periods and 2 exam periods (1 week each).

    Structure:
    - 6 marking periods equally distributed across the academic year
    - 2 exam periods (1 week each) at the end of each semester
    """
    today = datetime.now().date()
    academic_start = today.replace(day=1)  # First of current month

    # Calculate semester boundaries
    semester1_end = academic_start + relativedelta(months=6) - timedelta(days=1)
    semester2_start = academic_start + relativedelta(months=6)
    academic_end = academic_start + relativedelta(months=12) - timedelta(days=1)

    # Each marking period is approximately 2 months minus exam weeks
    # Semester 1: 6 months - 1 week exam = ~23 weeks, divided by 3 periods = ~7.67 weeks each
    # Semester 2: 6 months - 1 week exam = ~23 weeks, divided by 3 periods = ~7.67 weeks each

    marking_periods = []

    # First Semester Marking Periods (3 periods + 1 exam)
    period_duration_weeks = 7  # approximately 7 weeks per period

    # Marking Period 1
    mp1_start = academic_start
    mp1_end = mp1_start + timedelta(weeks=period_duration_weeks) - timedelta(days=1)

    # Marking Period 2
    mp2_start = mp1_end + timedelta(days=1)
    mp2_end = mp2_start + timedelta(weeks=period_duration_weeks) - timedelta(days=1)

    # Marking Period 3
    mp3_start = mp2_end + timedelta(days=1)
    mp3_end = mp3_start + timedelta(weeks=period_duration_weeks) - timedelta(days=1)

    # Semester 1 Exam (1 week)
    exam1_start = mp3_end + timedelta(days=1)
    exam1_end = exam1_start + timedelta(weeks=1) - timedelta(days=1)

    # Second Semester Marking Periods (3 periods + 1 exam)
    # Marking Period 4
    mp4_start = semester2_start
    mp4_end = mp4_start + timedelta(weeks=period_duration_weeks) - timedelta(days=1)

    # Marking Period 5
    mp5_start = mp4_end + timedelta(days=1)
    mp5_end = mp5_start + timedelta(weeks=period_duration_weeks) - timedelta(days=1)

    # Marking Period 6
    mp6_start = mp5_end + timedelta(days=1)
    mp6_end = mp6_start + timedelta(weeks=period_duration_weeks) - timedelta(days=1)

    # Semester 2 Exam (1 week)
    exam2_start = mp6_end + timedelta(days=1)
    exam2_end = exam2_start + timedelta(weeks=1) - timedelta(days=1)

    return [
        {
            "name": "Marking Period 1",
            "short_name": "MP 1",
            "start_date": mp1_start.strftime("%Y-%m-%d"),
            "end_date": mp1_end.strftime("%Y-%m-%d"),
            "semester": 0,
        },
        {
            "name": "Marking Period 2",
            "short_name": "MP 2",
            "start_date": mp2_start.strftime("%Y-%m-%d"),
            "end_date": mp2_end.strftime("%Y-%m-%d"),
            "semester": 0,
        },
        {
            "name": "Marking Period 3",
            "short_name": "MP 3",
            "start_date": mp3_start.strftime("%Y-%m-%d"),
            "end_date": mp3_end.strftime("%Y-%m-%d"),
            "semester": 0,
        },
        {
            "name": "Semester 1 Exam",
            "short_name": "Sem 1 Exam",
            "start_date": exam1_start.strftime("%Y-%m-%d"),
            "end_date": exam1_end.strftime("%Y-%m-%d"),
            "semester": 0,
        },
        {
            "name": "Marking Period 4",
            "short_name": "MP 4",
            "start_date": mp4_start.strftime("%Y-%m-%d"),
            "end_date": mp4_end.strftime("%Y-%m-%d"),
            "semester": 1,
        },
        {
            "name": "Marking Period 5",
            "short_name": "MP 5",
            "start_date": mp5_start.strftime("%Y-%m-%d"),
            "end_date": mp5_end.strftime("%Y-%m-%d"),
            "semester": 1,
        },
        {
            "name": "Marking Period 6",
            "short_name": "MP 6",
            "start_date": mp6_start.strftime("%Y-%m-%d"),
            "end_date": mp6_end.strftime("%Y-%m-%d"),
            "semester": 1,
        },
        {
            "name": "Semester 2 Exam",
            "short_name": "Sem 2 Exam",
            "start_date": exam2_start.strftime("%Y-%m-%d"),
            "end_date": exam2_end.strftime("%Y-%m-%d"),
            "semester": 1,
        },
    ]


# For backward compatibility
marking_periods_dict = get_marking_periods_dict()

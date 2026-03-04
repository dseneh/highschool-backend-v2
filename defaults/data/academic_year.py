from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta


def get_academic_year():
    """
    Generate academic year data starting from the first of current month for 12 months.
    """
    today = datetime.now().date()
    start_date = today.replace(day=1)  # First of current month
    end_date = (
        start_date + relativedelta(months=12) - timedelta(days=1)
    )  # 12 months later minus 1 day

    return {
        "name": f"{start_date.year}-{end_date.year}",
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "current": True,
    }


# For backward compatibility
academic_year = get_academic_year()

"""Default seed data for the `payroll` module.

Seeded at tenant creation so the tenant has a usable default pay schedule
ready for assigning to employees.
"""

from datetime import date
from decimal import Decimal


def get_default_pay_schedule():
    """Return the default monthly pay schedule definition.

    `currency` is resolved at seed time from the tenant's base
    AccountingCurrency.
    """
    today = date.today()
    return {
        "name": "Monthly Payroll",
        "frequency": "monthly",
        "anchor_date": date(today.year, today.month, 1),
        "payment_day_offset": 0,
        "overtime_multiplier": Decimal("1.50"),
        "is_default": True,
        "is_active": True,
    }

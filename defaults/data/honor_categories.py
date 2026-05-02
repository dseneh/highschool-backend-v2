"""Default seed data for `grading.HonorCategory`."""

from decimal import Decimal


honor_categories = [
    {
        "label": "Principal's List",
        "min_average": Decimal("95.00"),
        "max_average": Decimal("100.00"),
        "color": "#facc15",  # amber-400
        "icon": "trophy",
        "order": 1,
    },
    {
        "label": "Honor Roll",
        "min_average": Decimal("90.00"),
        "max_average": Decimal("94.99"),
        "color": "#22c55e",  # green-500
        "icon": "award",
        "order": 2,
    },
    {
        "label": "Honorable Mention",
        "min_average": Decimal("85.00"),
        "max_average": Decimal("89.99"),
        "color": "#3b82f6",  # blue-500
        "icon": "medal",
        "order": 3,
    },
    {
        "label": "Merit",
        "min_average": Decimal("80.00"),
        "max_average": Decimal("84.99"),
        "color": "#8b5cf6",  # violet-500
        "icon": "star",
        "order": 4,
    },
]

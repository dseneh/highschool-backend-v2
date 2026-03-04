"""
Default assessment types for grading system.
"""

assessment_types_data = [
    {
        "name": "Assignment",
        "description": "Regular homework or class assignments",
        "is_single_entry": False,
    },
    {
        "name": "Quiz",
        "description": "Short assessments covering recent material",
        "is_single_entry": False,
    },
    {
        "name": "Test",
        "description": "Comprehensive unit or chapter tests",
        "is_single_entry": False,
    },
    {
        "name": "Midterm Exam",
        "description": "Mid-semester examination",
        "is_single_entry": False,
    },
    {
        "name": "Final Exam",
        "description": "End of semester examination",
        "is_single_entry": False,
    },
    {
        "name": "Project",
        "description": "Long-term projects and presentations",
        "is_single_entry": False,
    },
    {
        "name": "Lab Work",
        "description": "Laboratory exercises and experiments",
        "is_single_entry": False,
    },
    {
        "name": "Participation",
        "description": "Class participation and engagement",
        "is_single_entry": False,
    },
    {
        "name": "Final Grade",
        "description": "Single-entry final grade for the marking period",
        "is_single_entry": True,
    },
]

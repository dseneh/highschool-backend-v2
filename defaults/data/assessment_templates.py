"""
Default assessment templates for grading system.
These templates are used to auto-generate assessments for each gradebook.
"""

assessment_templates_data = [
    # Marking Period Assessments (Regular periods: MP1, MP2, MP3, MP5, MP6, MP7)
    {
        "name": "Quiz 1",
        "assessment_type_name": "Quiz",
        "max_score": 100,
        "weight": 1,
        "is_calculated": True,
        "order": 1,
        "description": "First quiz of the marking period",
        "target": "marking_period",
    },
    {
        "name": "Quiz 2",
        "assessment_type_name": "Quiz",
        "max_score": 100,
        "weight": 1,
        "is_calculated": True,
        "order": 2,
        "description": "Second quiz of the marking period",
        "target": "marking_period",
    },
    {
        "name": "Assignment 1",
        "assessment_type_name": "Assignment",
        "max_score": 100,
        "weight": 1,
        "is_calculated": True,
        "order": 3,
        "description": "First assignment",
        "target": "marking_period",
    },
    {
        "name": "Assignment 2",
        "assessment_type_name": "Assignment",
        "max_score": 100,
        "weight": 1,
        "is_calculated": True,
        "order": 4,
        "description": "Second assignment",
        "target": "marking_period",
    },
    {
        "name": "Test",
        "assessment_type_name": "Test",
        "max_score": 100,
        "weight": 2,
        "is_calculated": True,
        "order": 5,
        "description": "Unit or chapter test",
        "target": "marking_period",
    },
    {
        "name": "Participation",
        "assessment_type_name": "Participation",
        "max_score": 100,
        "weight": 1,
        "is_calculated": True,
        "order": 6,
        "description": "Class participation and engagement",
        "target": "marking_period",
    },
    
    # Exam Period Assessments (Semester exams: MP4, MP8)
    {
        "name": "Midterm Exam",
        "assessment_type_name": "Midterm Exam",
        "max_score": 100,
        "weight": 3,
        "is_calculated": True,
        "order": 1,
        "description": "Mid-semester examination",
        "target": "exam",
    },
    {
        "name": "Final Exam",
        "assessment_type_name": "Final Exam",
        "max_score": 100,
        "weight": 3,
        "is_calculated": True,
        "order": 1,
        "description": "End of semester examination",
        "target": "exam",
    },
]

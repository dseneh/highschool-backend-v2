from users.access_policies import BaseSchoolAccessPolicy


class AcademicsAccessPolicy(BaseSchoolAccessPolicy):
    """
    Permissions for academics-related endpoints:
      - AcademicYear, Division, GradeLevel, Semester, Subject
      - Section, SectionSubject, SectionSchedule
      - MarkingPeriod, Period, PeriodTime
      - GradeLevelTuition
    
    Academic configuration is managed by admin/registrar roles.
    """

    statements = [
        # 0) Anonymous users: read-only access
        {
            "action": ["list", "retrieve"],
            "principal": "anonymous",
            "effect": "allow",
        },

        # 0.05) Any authenticated user: read-only HTTP methods
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_safe_method",
        },

        # 0.1) Any authenticated user: read-only access (supports ViewSet + APIView GET)
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
        },

        # 1) SUPERADMIN / ADMIN: full access
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,superadmin",
        },

        # 2) REGISTRAR: full CRUD for academic configuration
        {
            "action": [
                "list",
                "retrieve",
                "create",
                "update",
                "partial_update",
                "destroy",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:registrar",
        },

        # 3) DATA_ENTRY: can create/update (but not delete) academic records
        {
            "action": [
                "list",
                "retrieve",
                "create",
                "update",
                "partial_update",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:data_entry",
        },

        # 4) TEACHER: can view and update their own schedules/sections
        {
            "action": [
                "list",
                "retrieve",
                "partial_update",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:teacher",
        },

        # 5) Special privilege: CORE_MANAGE -> full CRUD across all academic models
        {
            "action": [
                "list",
                "retrieve",
                "create",
                "update",
                "partial_update",
                "destroy",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_MANAGE",
        },

        # 6) Special privilege: CORE_VIEW -> read-only access
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_VIEW",
        },

        # 7) VIEWER: Read-only access (list and retrieve)
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:viewer",
        },

        # 8) STUDENT/PARENT: Can view academic year, marking periods, sections
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:student,parent",
        },
    ]

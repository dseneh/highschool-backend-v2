

from users.access_policies.access import BaseSchoolAccessPolicy


class StudentAccessPolicy(BaseSchoolAccessPolicy):
    """
    Permissions for student-related endpoints:
      - students_student
      - students_enrollment
      - students_attendance
      - students_gradebook
      - students_studentenrollmentbill
      - students_studentpaymentsummary
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

        # 1) SUPERADMIN / TENANT_ADMIN: full access across tenants
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin",
        },

        # 2) ADMIN & REGISTRAR: full manage rights by default
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
            "condition": "is_role_in:registrar,data_entry",
        },

        # 3) DATA_ENTRY: can list/retrieve and modify basic records (but not delete)
        # {
        #     "action": [
        #         "list",
        #         "retrieve",
        #         "create",
        #         "update",
        #         "partial_update",
        #     ],
        #     "principal": "authenticated",
        #     "effect": "allow",
        #     "condition": "is_role_in:data_entry",
        # },

        # 4) Special privileges (per-user, can be granted/revoked dynamically)
        # STUDENT_ENROLL -> create enrollment records
        {
            "action": ["create"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:STUDENT_ENROLL",
        },

        # STUDENT_EDIT -> update student/enrollment/attendance
        {
            "action": ["update", "partial_update"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_any_privilege:STUDENT_EDIT,STUDENT_ENROLL",
        },

        # STUDENT_DELETE -> delete student/enrollment/attendance records
        {
            "action": ["destroy"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:STUDENT_DELETE",
        },

        # Optionally: STUDETNS_MANAGE to cover all CRUD within students app
        # {
        #     "action": [
        #         "list",
        #         "retrieve",
        #         "create",
        #         "update",
        #         "partial_update",
        #         "destroy",
        #     ],
        #     "principal": "authenticated",
        #     "effect": "allow",
        #     "condition": "has_privilege:STUDENTS_MANAGE",
        # },
        # VIEWER: Read-only access (list and retrieve)
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:viewer",
        },
    ]

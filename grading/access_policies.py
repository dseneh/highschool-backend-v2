from users.access_policies import BaseSchoolAccessPolicy


class GradebookAccessPolicy(BaseSchoolAccessPolicy):
    """
    Permissions for grading operations:
      - grading.enter  -> create/update/bulk_enter
      - grading.review -> review
      - grading.approve-> approve
      - grading.reject -> reject
    Applies to grading_assessment, grading_gradebook, grading_grade, etc.

        Note:
            Many grading endpoints are APIView-based and expose HTTP-method actions
            (post/put/patch/delete) instead of ViewSet actions
            (create/update/partial_update/destroy). Include both forms.
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

        # 1) SUPERADMIN / TENANT_ADMIN: full grading control
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin",
        },

        # 2) SCHOOL_ADMINISTRATOR: full grading powers
        # {
        #     "action": [
        #         "list",
        #         "retrieve",
        #         "create",
        #         "update",
        #         "partial_update",
        #         "destroy",
        #         "bulk_enter",
        #         "review",
        #         "approve",
        #         "reject",
        #     ],
        #     "principal": "authenticated",
        #     "effect": "allow",
        #     "condition": "is_role_in:SCHOOL_ADMINISTRATOR",
        # },

        # 3a) REGISTRAR: enter only (review/approve require special privilege)
        {
            "action": [
                "list",
                "retrieve",
                "get",
                "head",
                "options",
                "create",
                "update",
                "partial_update",
                "post",
                "put",
                "patch",
                "bulk_enter",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:registrar",
        },

        # 3b) TEACHER: role OR teaching-staff flag (Employee.is_teacher)
        {
            "action": [
                "list",
                "retrieve",
                "get",
                "head",
                "options",
                "create",
                "update",
                "partial_update",
                "post",
                "put",
                "patch",
                "bulk_enter",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_teacher_user",
        },

        # 4) Special privileges (per-user)
        # GRADING_ENTER -> create/update/bulk
        {
            "action": ["create", "update", "partial_update", "post", "put", "patch", "bulk_enter"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:GRADING_ENTER",
        },

        # GRADING_REVIEW -> review action
        {
            "action": ["review", "put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:GRADING_REVIEW",
        },

        # GRADING_APPROVE -> approve
        {
            "action": ["approve", "put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:GRADING_APPROVE",
        },

        # GRADING_REJECT -> reject
        {
            "action": ["reject", "put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:GRADING_REJECT",
        },

        # 5) GRADING_VIEW / GRADING_MANAGE for all grading models
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:GRADING_VIEW",
        },
        # VIEWER: Read-only access (list and retrieve)
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:viewer",
        },
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
        #     "condition": "has_privilege:GRADING_MANAGE",
        # },
    ]

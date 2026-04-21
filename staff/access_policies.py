from users.access_policies.access import BaseSchoolAccessPolicy


class StaffAccessPolicy(BaseSchoolAccessPolicy):
    """
    Permissions for staff-related endpoints:
      - staff_staff
      - staff_position
      - staff_positioncategory
      - staff_department
      - staff_teacherschedule
      - staff_teachersection
      - staff_teachersubject
    """

    statements = [
        # 0) Anonymous users: read-only access
        {
            "action": ["list", "retrieve"],
            "principal": "anonymous",
            "effect": "allow",
        },

        # 1) SUPERADMIN / ADMIN: full access
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,superadmin",
        },
        # 2) REGISTRAR & DATA_ENTRY: full manage rights by default
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
        {
            "action": [
                "destroy",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,superadmin",
        },
        # VIEWER: Read-only access (list and retrieve)
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:viewer",
        },
        # Privilege-based: full manage access
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_MANAGE",
        },
        # Privilege-based: read-only access
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_VIEW",
        },
    ]


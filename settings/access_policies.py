from users.access_policies import BaseSchoolAccessPolicy


class SettingsAccessPolicy(BaseSchoolAccessPolicy):
    """
    Permissions for settings management endpoints:
      - GradingSettingsView
      - SchoolGradingStyleView
      - GradingFixturesView
      - GradebookRegenerateView
    
    Settings configuration requires admin privileges.
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

        # 2) REGISTRAR: Can view and update grading settings
        {
            "action": [
                "list",
                "retrieve",
                "update",
                "partial_update",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:registrar",
        },

        # 3) Special privilege: SETTINGS_GRADING_MANAGE -> full grading settings CRUD
        {
            "action": [
                "list",
                "retrieve",
                "create",
                "update",
                "partial_update",
                "regenerate",
                "load_fixtures",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:SETTINGS_GRADING_MANAGE",
        },

        # 4) Special privilege: GRADING_MANAGE -> can view/update grading settings
        {
            "action": [
                "list",
                "retrieve",
                "update",
                "partial_update",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:GRADING_MANAGE",
        },

        # 5) VIEWER: Read-only access (list and retrieve)
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:viewer",
        },
    ]

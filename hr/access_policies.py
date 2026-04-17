from users.access_policies.access import BaseSchoolAccessPolicy


class HRAccessPolicy(BaseSchoolAccessPolicy):
    """Access rules for employee-first HR endpoints."""

    statements = [
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,superadmin",
        },
        {
            "action": [
                "list",
                "retrieve",
                "create",
                "update",
                "partial_update",
                "add_contact",
                "add_dependent",
                "by_number",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:registrar,data_entry",
        },
        {
            "action": ["list", "retrieve", "by_number"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:teacher,viewer",
        },
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_MANAGE",
        },
        {
            "action": ["list", "retrieve", "by_number"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_VIEW",
        },
    ]

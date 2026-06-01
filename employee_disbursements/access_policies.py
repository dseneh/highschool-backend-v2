from users.access_policies.access import BaseSchoolAccessPolicy


class EmployeeDisbursementsAccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,superadmin",
        },
        {
            "action": ["list", "retrieve", "ytd"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:registrar,data_entry,teacher,viewer",
        },
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_MANAGE",
        },
        {
            "action": ["list", "retrieve", "ytd"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_VIEW",
        },
    ]

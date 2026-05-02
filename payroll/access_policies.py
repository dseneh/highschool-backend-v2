from users.access_policies.access import BaseSchoolAccessPolicy


class PayrollAccessPolicy(BaseSchoolAccessPolicy):
    """Access rules for payroll endpoints.

    Mirrors HRAccessPolicy: admins/payroll-officers can mutate;
    teachers/viewers can only read.
    """

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
                "destroy",
                "next_period",
                "generate",
                "regenerate",
                "submit",
                "approve",
                "mark_paid",
                "preview",
                "recalculate",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:registrar,data_entry",
        },
        {
            "action": ["list", "retrieve"],
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
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_VIEW",
        },
    ]

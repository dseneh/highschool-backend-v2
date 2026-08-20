from users.access_policies import BaseSchoolAccessPolicy


class BudgetAccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["list", "retrieve", "summary", "baseline", "projections", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_any_privilege:BUDGET_VIEW,FINANCE_VIEW",
        },
        {
            "action": [
                "create", "update", "partial_update", "destroy", "submit", "reject",
                "bulk_enrollment_assumptions",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_any_privilege:BUDGET_MANAGE,FINANCE_MANAGE",
        },
        {
            "action": ["approve", "activate", "close"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:BUDGET_APPROVE",
        },
        {
            "action": ["list", "retrieve", "summary", "baseline", "projections", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:superadmin,admin,accountant",
        },
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:superadmin,admin,accountant",
        },
    ]

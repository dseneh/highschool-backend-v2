from users.access_policies import BaseSchoolAccessPolicy


class AccountingFinanceAccessPolicy(BaseSchoolAccessPolicy):
    """Access policy for accounting lookup/config endpoints."""

    statements = [
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
        },
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,accountant",
        },
    ]

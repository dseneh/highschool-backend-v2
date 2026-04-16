from users.access_policies import BaseSchoolAccessPolicy


class AccountingTransactionAccessPolicy(BaseSchoolAccessPolicy):
    """Access policy for accounting cash transaction endpoints."""

    statements = [
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
        },
        {
            "action": ["create", "update", "partial_update", "set_status", "approve", "reject"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,accountant,data_entry",
        },
        {
            "action": ["post_transaction"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,accountant",
        },
        {
            "action": ["destroy"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,accountant",
        },
    ]

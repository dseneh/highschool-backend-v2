from users.access_policies import BaseSchoolAccessPolicy


class AccountingTransactionAccessPolicy(BaseSchoolAccessPolicy):
    """Access policy for accounting cash transaction endpoints."""

    statements = [
        {
            # ``unposted_count`` is a tiny aggregate read; allowed for any
            # authenticated user so the sidebar badge can render for
            # everyone who can already see the transactions list.
            "action": [
                "list",
                "retrieve",
                "export_transactions",
                "unposted_count",
            ],
            "principal": "authenticated",
            "effect": "allow",
        },
        {
            "action": ["create", "update", "partial_update", "set_status", "approve", "reject", "bulk_upload", "upload", "upload_status"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,accountant,data_entry",
        },
        {
            # ``post_all`` is the bulk variant of ``post_transaction`` and
            # is gated by the same admin/accountant condition.
            "action": ["post_transaction", "post_all"],
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

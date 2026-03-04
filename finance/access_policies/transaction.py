from users.access_policies import BaseSchoolAccessPolicy


class TransactionAccessPolicy(BaseSchoolAccessPolicy):
    """
    Permissions for finance transactions:
      - finance_transaction + related finance models via FINANCE_* privileges.
    """

    statements = [
        # 0) Anonymous users: read-only access
        {
            "action": ["list", "retrieve"],
            "principal": "anonymous",
            "effect": "allow",
        },

        # 1) SUPERADMIN / TENANT_ADMIN: full finance control
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,accountant",
        },
        # 2) SCHOOL_ADMINISTRATOR: full CRUD & approve/cancel by role
        # {
        #     "action": [
        #         "list",
        #         "retrieve",
        #         "create",
        #         "update",
        #         "partial_update",
        #         "destroy",
        #         "approve",
        #         "cancel",
        #         "delete",
        #         "set_status",
        #         "bulk_create",
        #         "account_transfer",
        #         "delete_by_reference",
        #         "student_transactions",
        #     ],
        #     "principal": "authenticated",
        #     "effect": "allow",
        #     "condition": "is_role_in:SCHOOL_ADMINISTRATOR",
        # },
        # 3) ACCOUNTANT: full finance CRUD
        # {
        #     "action": [
        #         "list",
        #         "retrieve",
        #         "create",
        #         "update",
        #         "partial_update",
        #         "destroy",
        #         "approve",
        #         "cancel",
        #         "delete",
        #         "set_status",
        #         "bulk_create",
        #         "account_transfer",
        #         "delete_by_reference",
        #         "student_transactions",
        #     ],
        #     "principal": "authenticated",
        #     "effect": "allow",
        #     "condition": "is_role_in:accountant",
        # },
        # 4) DATA_ENTRY: can create/update, but not delete/approve/cancel by role
        {
            "action": [
                "list",
                "retrieve",
                "create",
                "update",
                "partial_update",
                "bulk_create",
                "student_transactions",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:data_entry",
        },
        {
            "action": [
                "student_transactions",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:student",
        },
        # 5) Special per-user privileges (for ANY role if you want)
        # {
        #     "action": [
        #         "create",
        #         "bulk_create",
        #         "account_transfer",
        #         "update",
        #         "partial_update",
        #     ],
        #     "principal": "authenticated",
        #     "effect": "allow",
        #     "condition": "is_role_in:admin,accountant",
        # },
        # {
        #     "action": ["update", "partial_update"],
        #     "principal": "authenticated",
        #     "effect": "allow",
        #     "condition": "has_privilege:TRANSACTION_UPDATE",
        # },
        {
            "action": ["destroy", "delete", "delete_by_reference"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:TRANSACTION_DELETE",
        },
        {
            "action": ["approve", "set_status"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:TRANSACTION_APPROVE",
        },
        {
            "action": ["cancel", "set_status"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:TRANSACTION_CANCEL",
        },
        # 6) FINANCE_VIEW / FINANCE_MANAGE overrides for all finance models
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:FINANCE_VIEW",
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
        #         "approve",
        #         "cancel",
        #         "delete",
        #         "set_status",
        #         "bulk_create",
        #         "account_transfer",
        #         "delete_by_reference",
        #         "student_transactions",
        #     ],
        #     "principal": "authenticated",
        #     "effect": "allow",
        #     "condition": "has_privilege:FINANCE_MANAGE",
        # },
    ]

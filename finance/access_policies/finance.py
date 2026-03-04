from users.access_policies import BaseSchoolAccessPolicy


class FinanceAccessPolicy(BaseSchoolAccessPolicy):
    """
    Permissions for finance configuration endpoints:
      - BankAccount, Currency, PaymentMethod, TransactionType
      - GeneralFee, SectionFee, PaymentInstallment
      - StudentPaymentStatus
    
    Finance configuration managed by admin/accountant roles.
    Transaction actions are in TransactionAccessPolicy.
    """

    statements = [
        # 0) Anonymous users: read-only access
        {
            "action": ["list", "retrieve"],
            "principal": "anonymous",
            "effect": "allow",
        },

        # 0.05) Any authenticated user: read-only HTTP methods
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_safe_method",
        },

        # 0.1) Any authenticated user: read-only access (supports ViewSet + APIView GET)
        {
            "action": ["list", "retrieve", "get", "head", "options"],
            "principal": "authenticated",
            "effect": "allow",
        },

        # 1) SUPERADMIN / ADMIN: full access
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,superadmin",
        },

        # 2) ACCOUNTANT: full CRUD for finance configuration
        {
            "action": [
                "list",
                "retrieve",
                "create",
                "update",
                "partial_update",
                "destroy",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:accountant",
        },

        # 3) REGISTRAR: can view and create/update fees (but not delete)
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
            "condition": "is_role_in:registrar",
        },

        # 4) DATA_ENTRY: can view and create/update basic finance records
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
            "condition": "is_role_in:data_entry",
        },

        # 5) Special privilege: FINANCE_MANAGE -> full CRUD
        {
            "action": [
                "list",
                "retrieve",
                "create",
                "update",
                "partial_update",
                "destroy",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:FINANCE_MANAGE",
        },

        # 6) Special privilege: FINANCE_VIEW -> read-only access
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:FINANCE_VIEW",
        },

        # 7) VIEWER: Read-only access (list and retrieve)
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:viewer",
        },

        # 8) STUDENT/PARENT: Can view their own payment status and fees
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:student,parent",
        },
    ]

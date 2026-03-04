from users.access_policies import BaseSchoolAccessPolicy


class ReportsAccessPolicy(BaseSchoolAccessPolicy):
    """
    Permissions for report generation endpoints:
      - StudentReportView
      - TransactionReportView
      - FinanceReportView
    
    Reports typically require elevated permissions to view sensitive data.
    """

    statements = [
        # 0) Anonymous users: read-only access
        {
            "action": ["list", "retrieve"],
            "principal": "anonymous",
            "effect": "allow",
        },

        # 1) SUPERADMIN / ADMIN: full access to all reports
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,superadmin",
        },

        # 2) REGISTRAR: Can view student reports
        {
            "action": ["list", "retrieve", "export", "download"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:registrar",
        },

        # 3) ACCOUNTANT: Can view finance/transaction reports
        {
            "action": ["list", "retrieve", "export", "download"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:accountant",
        },

        # 4) TEACHER: Can view student reports for their sections
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:teacher",
        },

        # 5) Special privilege: STUDENTS_VIEW -> can view student reports
        {
            "action": ["list", "retrieve", "export", "download"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:STUDENTS_VIEW",
        },

        # 6) Special privilege: FINANCE_VIEW -> can view finance reports
        {
            "action": ["list", "retrieve", "export", "download"],
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
    ]

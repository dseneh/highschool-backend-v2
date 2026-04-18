from users.access_policies import BaseSchoolAccessPolicy


class AuditLogAccessPolicy(BaseSchoolAccessPolicy):
    """
    Read-only access to audit logs – restricted to admin and viewer roles.
    """

    statements = [
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,viewer",
        },
    ]

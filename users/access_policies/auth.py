from users.access_policies.access import BaseSchoolAccessPolicy


class AuthAccessPolicy(BaseSchoolAccessPolicy):
    """
    Access policy for authentication endpoints.
    
    Rules:
    - Login endpoint: Allows anonymous (unauthenticated) users
    - Password reset endpoints: Allows anonymous (unauthenticated) users
    - Password default reset: Requires authentication (handled by UserAccessPolicy)
    """

    statements = [
        # Allow anonymous users to login
        {
            "action": ["login"],
            "principal": "anonymous",
            "effect": "allow",
        },
        # Allow anonymous users to request password reset
        {
            "action": ["password_reset"],
            "principal": "anonymous",
            "effect": "allow",
        },
        # Allow anonymous users to confirm password reset (with token)
        {
            "action": ["password_reset_confirm"],
            "principal": "anonymous",
            "effect": "allow",
        },
    ]


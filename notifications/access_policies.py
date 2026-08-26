from users.access_policies.access import BaseSchoolAccessPolicy


class NotificationAccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        # Read-only inbox views for any authenticated user. ``summary`` and
        # ``unread_count`` are DRF @action endpoints, so they show up as
        # action names (not the generic ``list``/``retrieve``). HTTP-method
        # names (``get``, ``head``, ``options``) cover the APIView routes
        # (announcements, preferences, tenant settings).
        {
            "action": [
                "list",
                "retrieve",
                "summary",
                "unread_count",
                "banners",
                "get",
                "head",
                "options",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_safe_method",
        },
        {
            "action": ["mark_read", "mark_all_read", "dismiss_banner"],
            "principal": "authenticated",
            "effect": "allow",
        },
        {
            "action": ["create", "list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,registrar",
        },
        {
            "action": ["create"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:notifications.send",
        },
        {
            "action": ["create"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:notifications.send_class",
        },
        {
            "action": ["create"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:teacher",
        },
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin",
        },
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:notifications.manage",
        },
    ]

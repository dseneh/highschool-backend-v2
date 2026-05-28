from users.access_policies.access import BaseSchoolAccessPolicy


class PayrollV2AccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin,superadmin",
        },
        {
            "action": [
                "list",
                "retrieve",
                "create",
                "update",
                "partial_update",
                "destroy",
                "get",
                "patch",
                "post",
                "put",
                "delete",
            "generate",
            "submit",
            "approve",
            "mark_paid",
            "revert_to_draft",
            "recalculate",
            "next_period",
            "sync_employees",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:registrar,data_entry",
        },
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:teacher,viewer",
        },
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_MANAGE",
        },
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_privilege:CORE_VIEW",
        },
    ]

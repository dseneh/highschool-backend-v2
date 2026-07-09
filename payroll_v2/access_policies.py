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
            "download_pdf",
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

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        tenant = self._current_tenant()
        if not tenant:
            return True
        from billing.services.access import tenant_has_payroll

        return tenant_has_payroll(tenant)

    @staticmethod
    def _current_tenant():
        from django.db import connection

        from core.models import Tenant

        schema = connection.schema_name
        if not schema or schema == "public":
            return None
        return Tenant.objects.filter(schema_name=schema).first()

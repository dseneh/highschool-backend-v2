from users.access_policies.access import BaseSchoolAccessPolicy


class PayrollV2AccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_own_employee_pay",
        },
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
            "complete",
            "cancel",
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
            "action": ["record_payment"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:finance,accountant",
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
            "condition": "has_rbac_permission:payroll.configure",
        },
        {
            "action": ["list", "retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:payroll.view",
        },
    ]

    def is_own_employee_pay(self, request, view, action):
        from hr.self_service import own_employee_queryset
        from payroll_v2.views import EmployeeCompensationViewSet, EmployeePayrollItemViewSet, PayrollEmployeeItemViewSet
        if not isinstance(view, (EmployeeCompensationViewSet, EmployeePayrollItemViewSet, PayrollEmployeeItemViewSet)):
            return False
        employee_ids = {str(employee.pk) for employee in own_employee_queryset(request.user)}
        if action == "list":
            return request.query_params.get("employee") in employee_ids
        from uuid import UUID
        try:
            pk = UUID(str(view.kwargs.get("pk")))
        except (ValueError, TypeError):
            return False
        # Keep existing paid-paystub visibility and queryset restrictions.
        return view.get_queryset().filter(pk=pk, employee_id__in=employee_ids).exists()

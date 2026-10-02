from users.access_policies.access import BaseSchoolAccessPolicy


class HRAccessPolicy(BaseSchoolAccessPolicy):
    """Access rules for employee-first HR endpoints."""

    statements = [
        {
            "action": ["list", "create"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_own_employee_records",
        },
        {
            "action": ["me", "retrieve", "update", "partial_update"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_own_employee_profile",
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
                "add_contact",
                "add_dependent",
                "by_number",
            ],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:registrar,data_entry",
        },
        {
            "action": ["list", "retrieve", "by_number"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:teacher,viewer",
        },
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:hr.manage",
        },
        {
            "action": ["list", "retrieve", "by_number"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:hr.view",
        },
    ]

    def is_own_employee_profile(self, request, view, action):
        # This exception applies only to the caller's employee profile, never
        # to the other HR resources that share this policy.
        from hr.views import EmployeeViewSet
        from hr.self_service import own_employee_queryset, PERSONAL_FIELDS
        if not isinstance(view, EmployeeViewSet):
            return False
        if action == "me":
            return True
        lookup = str(view.kwargs.get("pk", ""))
        employee = next((item for item in own_employee_queryset(request.user)
                         if lookup in {str(item.pk), item.id_number}), None)
        if employee is None:
            return False
        if action in {"update", "partial_update"}:
            return set(request.data).issubset(PERSONAL_FIELDS)
        return action == "retrieve"

    def is_own_employee_records(self, request, view, action):
        from hr.views import (EmployeeAttendanceViewSet, EmployeePerformanceReviewViewSet,
                              EmployeeSpecializationViewSet, LeaveRequestViewSet, LeaveTypeViewSet)
        from hr.self_service import own_employee_queryset
        allowed = (EmployeeAttendanceViewSet, EmployeePerformanceReviewViewSet,
                   EmployeeSpecializationViewSet, LeaveRequestViewSet)
        if isinstance(view, LeaveTypeViewSet) and action == "list":
            return own_employee_queryset(request.user).exists()
        if not isinstance(view, allowed):
            return False
        if action == "create":
            if not isinstance(view, LeaveRequestViewSet):
                return False
            if not set(request.data).issubset({"employee", "leave_type", "start_date", "end_date", "reason"}):
                return False
            identifier = request.data.get("employee")
        else:
            identifier = request.query_params.get("employee")
            if not isinstance(view, EmployeeSpecializationViewSet):
                identifier = identifier or request.query_params.get("employee_id")
        return bool(identifier) and any(str(employee.pk) == str(identifier) for employee in own_employee_queryset(request.user))

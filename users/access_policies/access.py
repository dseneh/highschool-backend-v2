# users/access_policies.py

from typing import List

from django.db.models import Q
from rest_access_policy import AccessPolicy
from rest_framework.permissions import SAFE_METHODS

from common.status import Roles  # your role enum
from users.models import User
from users.tenant_access import is_global_superadmin


class BaseSchoolAccessPolicy(AccessPolicy):
    """
    Base access policy for all school-related endpoints.

    Provides helper conditions:
      - is_role_in:SUPERADMIN,TENANT_ADMIN
            - is_teacher_user
    - has_rbac_permission:grades.approve
    - has_any_rbac_permission:grades.enter,grades.review
    """

    # Default: everything is denied unless explicitly allowed by subclass statements.
    statements = [
        {
            "action": ["*"],
            "principal": "*",
            "effect": "deny",
        }
    ]

    def _has_unrestricted_access(self, request) -> bool:
        user = self._get_user(request)
        if not user:
            return False
        if is_global_superadmin(user):
            return True

        from authorization.runtime import initialize_request_authorization

        return initialize_request_authorization(request, user).context.unrestricted

    def has_permission(self, request, view) -> bool:
        if self._has_unrestricted_access(request):
            return True
        return super().has_permission(request, view)

    def has_object_permission(self, request, view, obj) -> bool:
        if self._has_unrestricted_access(request):
            return True
        return super().has_object_permission(request, view, obj)

    # --- helper condition methods used by AccessPolicy JSON-like statements ---

    def _normalize_code(self, value: str) -> str:
        return (value or "").strip().upper()

    def _get_user(self, request) -> User | None:
        user: User | None = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        return user

    def _get_invoked_action(self, view) -> str:
        """
        For ViewSets, keep DRF action resolution.
        For APIViews, use the HTTP method so policy statements can match
        `get/post/put/patch/delete` consistently instead of class names.
        """
        if hasattr(view, "action"):
            if hasattr(view, "action_map"):
                return view.action or list(view.action_map.values())[0]
            return view.action

        request = getattr(view, "request", None)
        method = getattr(request, "method", None)
        if method:
            method = method.lower()
            action_map = getattr(view, "policy_action_map", None)
            if isinstance(action_map, dict):
                return action_map.get(method, method)
            return method

        return super()._get_invoked_action(view)

    def is_role_in(self, request, view, action, roles: str) -> bool:
        """
        roles: comma-separated list of Role codes from common.status.Roles.
        Usage in statements: "condition": "is_role_in:SUPERADMIN,ADMIN"
        """
        user = self._get_user(request)
        if not user:
            return False

        if is_global_superadmin(user):
            return True

        from authorization.runtime import initialize_request_authorization

        authorization = initialize_request_authorization(request, user)
        role_key = authorization.context.role_id
        if not role_key:
            return False
        from authorization.models import Role

        system_key = Role.objects.filter(pk=role_key).values_list(
            "system_key", flat=True
        ).first()
        allowed: List[str] = [r.strip().lower() for r in roles.split(",") if r.strip()]
        return system_key in allowed

    def has_rbac_permission(self, request, view, action, permission_code: str) -> bool:
        """
        Returns True if the user has the given RBAC permission at all scope.
        Usage: "condition": "has_rbac_permission:grades.approve"
        """
        user = self._get_user(request)
        if not user:
            return False

        if is_global_superadmin(user):
            return True

        from authorization.runtime import initialize_request_authorization

        return initialize_request_authorization(request, user).permission_scope(
            permission_code
        ) == "all"

    def has_any_rbac_permission(self, request, view, action, permission_codes: str) -> bool:
        """
        Returns True if the user has ANY listed RBAC permission at all scope.
        Usage: "condition": "has_any_rbac_permission:grades.enter,grades.review"
        """
        user = self._get_user(request)
        if not user:
            return False

        if is_global_superadmin(user):
            return True

        from authorization.runtime import initialize_request_authorization

        permission_scope = initialize_request_authorization(
            request,
            user,
        ).permission_scope
        codes = [code.strip() for code in permission_codes.split(",") if code.strip()]
        return any(permission_scope(code) == "all" for code in codes)

    def is_teacher_user(self, request, view, action) -> bool:
        """
        True when the user is considered a teacher for grading access.

        A user qualifies as teacher when the linked staff or employee record is
        marked ``is_teacher=True``. Authorization remains RBAC-based.
        """
        user = self._get_user(request)
        if not user:
            return False

        from hr.models import Employee
        from staff.models import Staff

        employee = (
            Employee.objects.filter(
                Q(user_account_id_number=user.id_number) | Q(id_number=user.id_number)
            )
            .only("id", "is_teacher")
            .first()
        )
        if employee and employee.is_teacher:
            return True

        staff = (
            Staff.objects.filter(
                Q(user_account_id_number=user.id_number) | Q(id_number=user.id_number)
            )
            .only("id", "is_teacher")
            .first()
        )
        return bool(staff and staff.is_teacher)

    def is_safe_method(self, request, view, action) -> bool:
        """
        True for read-only HTTP methods.
        Useful for APIView endpoints where action names may vary.
        """
        return request.method in SAFE_METHODS

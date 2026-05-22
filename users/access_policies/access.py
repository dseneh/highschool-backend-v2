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
      - has_privilege:GRADING_APPROVE
      - has_any_privilege:GRADING_ENTER,GRADING_REVIEW
    """

    # Default: everything is denied unless explicitly allowed by subclass statements.
    statements = [
        {
            "action": ["*"],
            "principal": "*",
            "effect": "deny",
        }
    ]

    # --- helper condition methods used by AccessPolicy JSON-like statements ---

    def _normalize_code(self, value: str) -> str:
        return (value or "").strip().upper()

    def _normalize_role(self, value: str) -> str:
        return (value or "").strip().lower()

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
            return method.lower()

        return super()._get_invoked_action(view)

    def is_role_in(self, request, view, action, roles: str) -> bool:
        """
        roles: comma-separated list of Role codes from common.status.Roles.
        Usage in statements: "condition": "is_role_in:SUPERADMIN,ADMIN"
        """
        user = self._get_user(request)
        if not user:
            return False

        user_role = self._normalize_role(getattr(user, "role", ""))

        if is_global_superadmin(user) or user.is_superuser:
            return True

        allowed: List[str] = [self._normalize_role(r) for r in roles.split(",") if r.strip()]
        # underlying value of Roles.* should match User.role
        return user_role in allowed

    def has_privilege(self, request, view, action, privilege_code: str) -> bool:
        """
        Returns True if the user has the given privilege code.
        Usage: "condition": "has_privilege:GRADING_APPROVE"
        """
        user = self._get_user(request)
        if not user:
            return False

        return user.has_privilege(self._normalize_code(privilege_code))

    def has_any_privilege(self, request, view, action, privilege_codes: str) -> bool:
        """
        Returns True if the user has ANY of the given privilege codes.
        Usage: "condition": "has_any_privilege:GRADING_ENTER,GRADING_REVIEW"
        """
        user = self._get_user(request)
        if not user:
            return False

        codes = [self._normalize_code(c) for c in privilege_codes.split(",") if c.strip()]
        user_privileges = set(user.get_privileges())
        return any(code in user_privileges for code in codes)

    def is_teacher_user(self, request, view, action) -> bool:
        """
        True when the user is considered a teacher for grading access.

        A user qualifies as teacher if either:
        - user.role is teacher, OR
        - the linked staff record is marked is_teacher=True.
        """
        user = self._get_user(request)
        if not user:
            return False

        if self._normalize_role(getattr(user, "role", "")) == self._normalize_role(Roles.TEACHER):
            return True

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

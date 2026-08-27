import logging

from rest_framework.permissions import BasePermission

from authorization.runtime import initialize_request_authorization


logger = logging.getLogger(__name__)

TENANT_ADMIN_ROLE_MANAGEMENT_PERMISSIONS = {
    "roles.create",
    "roles.assign_users",
}


def _is_tenant_admin_context(facade) -> bool:
    context = facade.context
    if not context.active or not context.role_id:
        return False
    try:
        from authorization.models import Role

        return Role.objects.filter(
            pk=context.role_id,
            system_key="admin",
            is_active=True,
        ).exists()
    except Exception:
        logger.exception("Tenant admin role fallback evaluation failed")
        return False


class RBACPermission(BasePermission):
    message = "You do not have permission to perform this action."

    @staticmethod
    def _action(request, view) -> str | None:
        if hasattr(view, "action"):
            return view.action
        method = getattr(request, "method", "")
        return method.lower() if method else None

    def _permission_code(self, request, view) -> str | None:
        permission_map = getattr(view, "permission_map", None)
        if not isinstance(permission_map, dict):
            return None
        action = self._action(request, view)
        permission_code = permission_map.get(action)
        return permission_code if isinstance(permission_code, str) else None

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        permission_code = self._permission_code(request, view)
        if permission_code is None:
            return False
        try:
            facade = initialize_request_authorization(request, user)
            scope = facade.permission_scope(permission_code)
            if scope is None:
                return (
                    permission_code in TENANT_ADMIN_ROLE_MANAGEMENT_PERMISSIONS
                    and _is_tenant_admin_context(facade)
                )
            if scope == "all":
                return True

            action = self._action(request, view)
            object_actions = {"retrieve", "update", "partial_update", "destroy"}
            if hasattr(view, "action") and action in object_actions:
                return True

            scope_checker = getattr(view, "has_rbac_action_scope", None)
            if not callable(scope_checker):
                return False
            return bool(
                scope_checker(
                    request=request,
                    permission=permission_code,
                    scope=scope,
                    action=action,
                )
            )
        except Exception:
            logger.exception("RBAC request permission evaluation failed")
            return False

    def has_object_permission(self, request, view, obj):
        permission_code = self._permission_code(request, view)
        if permission_code is None:
            return False
        try:
            facade = initialize_request_authorization(request, request.user)
            scope = facade.permission_scope(permission_code)
            if scope == "all":
                return True
            scope_checker = getattr(view, "has_rbac_object_scope", None)
            if not callable(scope_checker):
                return False
            return bool(
                scope_checker(
                    request=request,
                    obj=obj,
                    permission=permission_code,
                    scope=scope,
                )
            )
        except Exception:
            logger.exception("RBAC object permission evaluation failed")
            return False

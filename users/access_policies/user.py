from django.db.models import Q
from django.db import connection
from users.access_policies.access import BaseSchoolAccessPolicy
from common.status import Roles


class UserAccessPolicy(BaseSchoolAccessPolicy):
    """
    Access policy for user management endpoints.
    
    Rules:
    - SUPERADMIN: Can manage all users and assign any role
    - ADMIN: Can manage users in their tenant and assign roles (except superadmin)
    - Others: Limited access based on privileges
    """

    statements = [
        # Any signed-in user can read their own profile from GET /auth/users/current/
        {
            "action": ["get"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_current_user_endpoint",
        },
        # User management is permission-based for all non-superadmins.
        {
            "action": ["list", "retrieve", "tenants"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:users.view",
        },
        {
            "action": ["create", "recreate"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:users.create",
        },
        {
            "action": ["post"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "can_create_global_user",
        },
        {
            "action": ["update", "partial_update", "password_admin_set", "password_default"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:users.update",
        },
        {
            "action": ["destroy", "delete", "change_status"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:users.deactivate",
        },
        {
            "action": ["remove_tenant"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:roles.assign_users",
        },
        {
            "action": ["tenant_role"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "has_rbac_permission:roles.assign_users",
        },
        # Users can view their own profile
        {
            "action": ["retrieve", "current", "get"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_own_profile",
        },
        # Users can update their own profile and password
        {
            "action": ["update", "partial_update", "current", "password_change", "put", "patch", "post"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_own_profile",
        },
        # VIEWER: Read-only access (list and retrieve) for other users
        {
            "action": ["list", "retrieve", "current", "get"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:viewer",
        },
    ]

    def is_current_user_endpoint(self, request, view, action) -> bool:
        """True for the stateless current-user API (no id in the URL path)."""
        return view.__class__.__name__ == "CurrentUserView"

    def can_create_global_user(self, request, view, action) -> bool:
        if view.__class__.__name__ != "GlobalUserCreateView":
            return False
        return self.has_rbac_permission(
            request,
            view,
            action,
            "users.create",
        )

    def is_own_profile(self, request, view, action) -> bool:
        """Check if user is accessing their own profile"""
        user = self._get_user(request)
        if not user:
            return False

        if action == "current":
            return True
        
        # Check if the id_number in the URL matches the current user
        id_number = view.kwargs.get('id_number') or view.kwargs.get('pk')

        # GET /auth/users/current/ has no URL user id — always the authenticated user.
        if not id_number:
            return view.__class__.__name__ == 'CurrentUserView'
        
        # Direct match with 'current', user ID, id_number, or username
        # Convert to string for comparison to handle different types
        id_number_str = str(id_number).strip()
        
        if (id_number_str == 'current' or 
            id_number_str == str(user.id) or 
            id_number_str == user.id_number or 
            id_number_str == user.username):
            return True
        
        # Also try to resolve the user from the database if id_number doesn't match directly
        try:
            from users.models import User
            from django_tenants.utils import schema_context
            
            with schema_context('public'):
                target_user = User.objects.filter(
                    Q(id=id_number_str) | 
                    Q(id_number=id_number_str) | 
                    Q(username=id_number_str)
                ).first()
                
                if target_user and target_user.id == user.id:
                    return True
        except Exception:
            pass
        
        return False

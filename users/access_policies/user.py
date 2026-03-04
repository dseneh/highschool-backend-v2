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
        # SUPERADMIN: Full access to all users
        {
            "action": ["*"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:superadmin",
        },
        # ADMIN: Can list, retrieve, create, update, delete, and recreate users in their tenant
        {
            "action": ["list", "retrieve", "create", "update", "partial_update", "delete", "current", "password_change", "change_status", "password_reset_default", "password_reset_request", "password_reset_confirm", "recreate", "get", "post", "put", "patch"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_role_in:admin",
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

    def is_own_profile(self, request, view, action) -> bool:
        """Check if user is accessing their own profile"""
        user = self._get_user(request)
        if not user:
            return False
        
        # Check if the id_number in the URL matches the current user
        id_number = view.kwargs.get('id_number') or view.kwargs.get('pk')
        
        if not id_number:
            return False
        
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

    def can_assign_role(self, request, view, action, target_role: str = None) -> bool:
        """
        Check if user can assign a specific role.
        This is used for field-level validation in views.
        
        Args:
            target_role: The role being assigned (from request.data)
        """
        user = self._get_user(request)
        if not user:
            return False
        
        # SUPERADMIN can assign any role
        if user.role == Roles.SUPERADMIN or user.is_superuser:
            return True
        
        # ADMIN can assign roles (except superadmin) to users in their tenant
        if user.role == Roles.ADMIN:
            # Cannot assign superadmin role
            if target_role == Roles.SUPERADMIN:
                return False
            return True
        
        return False

    def can_assign_role_to_user(self, request, view, action, target_user_id: str = None, target_role: str = None) -> bool:
        """
        Check if user can assign a specific role to a specific user.
        This checks both role assignment permission and tenant restrictions.
        
        Args:
            target_user_id: ID of the user being updated
            target_role: The role being assigned
        """
        user = self._get_user(request)
        if not user:
            return False
        
        # SUPERADMIN can assign any role to any user
        if user.role == Roles.SUPERADMIN or user.is_superuser:
            return True
        
        # ADMIN can assign roles (except superadmin) to users in their tenant
        if user.role == Roles.ADMIN:
            # Cannot assign superadmin role
            if target_role == Roles.SUPERADMIN:
                return False
            
            # Check if target user is in the same tenant (multi-tenant check)
            if target_user_id:
                try:
                    from users.models import User
                    from django_tenants.utils import schema_context
                    from tenant_users.permissions.models import UserTenantPermissions
                    
                    with schema_context('public'):
                        target_user = User.objects.filter(
                            Q(id=target_user_id) | Q(id_number=target_user_id) | Q(username=target_user_id)
                        ).first()
                        
                        if not target_user:
                            return False
                    
                    # Check if both users are in the current tenant
                    if connection.schema_name != 'public':
                        user_in_tenant = UserTenantPermissions.objects.filter(profile=user).exists()
                        target_in_tenant = UserTenantPermissions.objects.filter(profile=target_user).exists()
                        
                        if user_in_tenant and target_in_tenant:
                            return True
                        return False
                    
                except Exception:
                    return False
            
            return True
        
        return False

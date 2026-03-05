"""
Custom DRF permission classes for role-based access control.

These classes check the user's custom 'role' field against system roles,
unlike Django's built-in IsAdminUser/IsStaff which check is_admin/is_staff fields.
"""

from rest_framework.permissions import BasePermission
from common.status import Roles


class IsSuperAdmin(BasePermission):
    """
    Permission check for superadmin users.
    
    Allows only users with role='superadmin'.
    Superadmins can perform any operation in the system.
    """
    message = "You must be a superadmin to perform this action."
    
    def has_permission(self, request, view):
        """Check if user is authenticated and has superadmin role"""
        return (
            request.user and
            request.user.is_authenticated and
            hasattr(request.user, 'role') and
            request.user.role == Roles.SUPERADMIN
        )


class IsAdminOrSuperAdmin(BasePermission):
    """
    Permission check for admin or superadmin users.
    
    Allows users with role='admin' or 'superadmin'.
    """
    message = "You must be an admin or superadmin to perform this action."
    
    def has_permission(self, request, view):
        """Check if user is authenticated and has admin or superadmin role"""
        return (
            request.user and
            request.user.is_authenticated and
            hasattr(request.user, 'role') and
            request.user.role in [Roles.ADMIN, Roles.SUPERADMIN]
        )


class HasPrivilege(BasePermission):
    """
    Permission check for users with specific privilege.
    
    Usage in ViewSet:
        permission_classes = [HasPrivilege]
        
        def get_permissions(self):
            if self.action == 'create':
                return [HasPrivilege(privilege_code='GRADING_APPROVE')]
            return super().get_permissions()
    
    Or use check_privilege method directly on the view.
    """
    message = "You do not have the required privilege for this action."
    
    def __init__(self, privilege_code=None):
        self.privilege_code = privilege_code
    
    def has_permission(self, request, view):
        """Check if user has the required privilege"""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Superadmin always has all privileges
        if hasattr(request.user, 'role') and request.user.role == Roles.SUPERADMIN:
            return True
        
        # If no specific privilege code is set, allow
        if not self.privilege_code:
            return True
        
        # Check if user has the privilege
        return request.user.has_privilege(self.privilege_code)

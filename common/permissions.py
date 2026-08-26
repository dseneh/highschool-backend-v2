"""
Custom DRF permission classes for role-based access control.

Platform permission classes. Tenant authorization is evaluated through RBAC memberships.
"""

from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    """
    Permission check for superadmin users.
    
    Allows only platform superusers.
    Superadmins can perform any operation in the system.
    """
    message = "You must be a superadmin to perform this action."
    
    def has_permission(self, request, view):
        """Check if the authenticated user is a platform superuser."""
        return (
            request.user and
            request.user.is_authenticated and
            request.user.is_platform_superuser
        )


class IsAdminOrSuperAdmin(BasePermission):
    """
    Permission check for admin or superadmin users.
    
    Allows platform superusers. Tenant administrators use RBAC permissions.
    """
    message = "You must be an admin or superadmin to perform this action."
    
    def has_permission(self, request, view):
        """Check if the authenticated user is a platform superuser."""
        return (
            request.user and
            request.user.is_authenticated and
            request.user.is_platform_superuser
        )


__all__ = ("IsAdminOrSuperAdmin", "IsSuperAdmin")

"""
User models for django-tenant-users
User model with UserProfile for multi-tenant user management

Reference: https://django-tenant-users.readthedocs.io/en/latest/pages/installation.html

Note: UserProfile from tenant_users.tenants.models already includes a user manager,
so we don't need to define a custom manager unless we want custom behavior.
"""

import uuid
from django.db import models
from django.contrib.auth.models import Group, Permission
from tenant_users.tenants.models import UserProfile
from core.validators import ValidateImageFile
from common.status import Roles, UserAccountType, PersonStatus
from .sso_models import (  # noqa: F401
    AuthenticationAuditEvent,
    AuthorizationCode,
    AuthorizationRequest,
    CentralAuthSession,
    OAuthClient,
    OAuthRedirectURI,
    RefreshToken,
    RefreshTokenFamily,
    SessionRevocation,
    TenantSession,
)


class User(UserProfile):
    """
    User model for django-tenant-users.
    
    Users are global (live in public schema) and can belong to multiple tenants.
    Tenant membership and roles are managed via TenantUser model.
    
    Reference: https://django-tenant-users.readthedocs.io/en/latest/pages/installation.html
    
    Key Points:
    - Inherits UserProfile (from tenant_users.tenants.models)
    - Uses UUID for id field (overrides UserProfile's default id)
    - Users are global (no tenant FK)
    - Roles are tenant-specific (stored in TenantUser model)
    - Photo is stored in public schema (users are global)
    """
    
    # Override id to use UUID (UserProfile uses auto-incrementing integer by default)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Additional user fields (UserProfile already provides email, etc.)
    username = models.CharField(max_length=150, unique=True, null=True, blank=True, help_text="Optional username for login")
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=10, choices=[('male', 'Male'), ('female', 'Female')], default='male')
    id_number = models.CharField(max_length=50, unique=True)
    account_type = models.CharField(
        max_length=20,
        choices=UserAccountType.choices(),
        default=UserAccountType.OTHER,
        help_text="Identity category only: global, staff, student, parent, or other. Authorization is tenant RBAC.",
    )
    status = models.CharField(
        max_length=20,
        choices=PersonStatus.choices(),
        default=PersonStatus.ACTIVE,
        help_text="User status: ACTIVE (default), INACTIVE, SUSPENDED, DELETED, etc."
    )
    
    # User photo - storage backend handles tenant-aware prefixing automatically
    photo = models.ImageField(
        upload_to="users",
        null=True,
        blank=True,
        help_text="User profile photo (storage backend handles tenant isolation)",
    )
    last_password_updated = models.DateTimeField(null=True, blank=True, help_text="Last password updated timestamp")
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        help_text="Time this user account was created.",
    )
    profile_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time profile or account details were updated.",
    )
    profile_updated_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profile_updates_made",
        help_text="User who last updated this account's profile details.",
    )
    is_default_password = models.BooleanField(default=False, help_text="Indicates whether this account is using its default password.")
    is_platform_superuser = models.BooleanField(
        default=False,
        help_text="Platform-wide administration flag. Tenant authorization uses RBAC memberships.",
    )
    groups = models.ManyToManyField(Group, blank=True, related_name='school_users', help_text='Groups for Django permission system')
    user_permissions = models.ManyToManyField(Permission, blank=True, related_name='school_users', help_text='Direct permissions for user')
    class Meta:
        db_table = "user"
        verbose_name = "User"
        verbose_name_plural = "Users"
    
    def __str__(self):
        return self.email or self.username or self.id_number or str(self.id)
    
    @property
    def is_admin(self) -> bool:
        """Whether this account is a platform administrator."""
        return bool(self.is_platform_superuser)
    
    @property
    def is_staff_user(self) -> bool:
        """Check if user is staff (has STAFF account type)"""
        return self.account_type == UserAccountType.STAFF
    
    @property
    def is_student_user(self) -> bool:
        """Check if user is student (has STUDENT account type)"""
        return self.account_type == UserAccountType.STUDENT
    
    @property
    def is_parent_user(self) -> bool:
        """Check if user is parent (has PARENT account type)"""
        return self.account_type == UserAccountType.PARENT
    
    # ---- Multi-Role Lookup Methods (No separate Account tables needed) ----
    
    def get_student(self):
        """
        Get associated Student record (if user is a student).
        Uses loose coupling via id_number reference.
        
        Returns:
            Student instance if found, None otherwise
        """
        if not self.is_student_user:
            return None
        try:
            from students.models import Student
            return Student.objects.get(user_account_id_number=self.id_number)
        except:
            return None
    
    def get_staff(self):
        """
        Get associated Staff record (if user is staff member).
        Uses loose coupling via id_number reference.
        
        Returns:
            Staff instance if found, None otherwise
        """
        if not self.is_staff_user:
            return None
        try:
            from staff.models import Staff
            return Staff.objects.get(user_account_id_number=self.id_number)
        except:
            return None
    
    def get_children(self):
        """
        Get student children (if user is a parent).
        Matches via StudentGuardian email field.
        
        Returns:
            QuerySet of Student records where this user is a guardian
        """
        if not self.is_parent_user:
            return None
        try:
            from students.models import Student, StudentGuardian
            student_ids = StudentGuardian.objects.filter(
                email=self.email
            ).values_list('student_id', flat=True)
            return Student.objects.filter(id__in=student_ids)
        except:
            return None
    
    def get_guardian_records(self):
        """
        Get all StudentGuardian records for this parent user.
        Matches via StudentGuardian email field.
        
        Returns:
            QuerySet of StudentGuardian instances
        """
        if not self.is_parent_user:
            return None
        try:
            from students.models import StudentGuardian
            return StudentGuardian.objects.filter(email=self.email)
        except:
            return None


# Tenant authorization roles and grants are modeled by the authorization app.

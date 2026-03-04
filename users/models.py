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
        help_text="User type: GLOBAL (system admin), TENANT (staff/student), or PARENT"
    )
    role = models.CharField(
        max_length=20,
        choices=Roles.choices(),
        default=Roles.VIEWER,
        help_text="User role: VIEWER (default), ADMIN, TEACHER, STUDENT, PARENT, etc."
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
        validators=[ValidateImageFile],
        help_text="User profile photo (storage backend handles tenant isolation)"
    )
    last_password_updated = models.DateTimeField(null=True, blank=True, help_text="Last password updated timestamp")
    is_default_password = models.BooleanField(default=False, help_text="Indicates if the user is using the default password. This is used to determine if the user needs to change their password on login.")

    
    # Django groups compatibility - for permission system integration
    groups = models.ManyToManyField(Group, blank=True, related_name='school_users', help_text='Groups for Django permission system')
    user_permissions = models.ManyToManyField(Permission, blank=True, related_name='school_users', help_text='Direct permissions for user')
    class Meta:
        db_table = "user"
        verbose_name = "User"
        verbose_name_plural = "Users"
    
    def __str__(self):
        return self.email or self.username or self.id_number or str(self.id)
    
    # ---- Permission/Privilege Helper Methods ----
    
    def has_privilege(self, privilege_code: str) -> bool:
        """
        Check if user has a specific privilege.
        
        Returns True if:
        - User is SUPERADMIN or is_superuser
        - User has privilege via special grant
        - User's role has privilege in RoleDefaultPrivilege
        
        Args:
            privilege_code: Code from permissions.PRIVILEGES (e.g., "GRADING_APPROVE")
            
        Returns:
            bool: True if user has privilege, False otherwise
        """
        # Superadmin always has all privileges
        if self.role == Roles.SUPERADMIN or self.is_superuser:
            return True
        
        # Check for explicit special privilege grant
        if self.special_privileges.filter(code=privilege_code).exists():
            return True
        
        # Check if role has this privilege by default
        return RoleDefaultPrivilege.objects.filter(
            role=self.role,
            privilege_code=privilege_code
        ).exists()
    
    def get_privileges(self) -> list[str]:
        """
        Get all privileges user holds (role defaults + special grants).
        
        Deduplicates and returns sorted list of privilege codes.
        
        Returns:
            list[str]: List of privilege codes (e.g., ["GRADING_ENTER", "STUDENTS_MANAGE"])
        """
        # Superadmin gets all privileges
        if self.role == Roles.SUPERADMIN or self.is_superuser:
            from users.access_policies.permissions import ALL_PRIVILEGE_CODES
            return ALL_PRIVILEGE_CODES
        
        # Get privileges from role defaults
        role_privileges = RoleDefaultPrivilege.objects.filter(
            role=self.role
        ).values_list("privilege_code", flat=True)
        
        # Get special privileges (exclude expired)
        from django.utils import timezone
        special_privileges = self.special_privileges.filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        ).values_list("code", flat=True)
        
        # Combine and deduplicate
        return sorted(list(set(role_privileges) | set(special_privileges)))
    
    def can_manage_user(self, target_user: "User") -> bool:
        """
        Check if this user can manage (edit/delete) target user.
        
        Rules:
        - SUPERADMIN can manage anyone
        - ADMIN can manage non-SUPERADMIN, non-ADMIN users
        - Others cannot manage anyone
        
        Args:
            target_user: User to check if manageable
            
        Returns:
            bool: True if current user can manage target user
        """
        if self.role == Roles.SUPERADMIN or self.is_superuser:
            return True
        
        if self.role == Roles.ADMIN:
            return target_user.role not in [Roles.SUPERADMIN, Roles.ADMIN]
        
        return False
    
    def can_grant_privilege(self, privilege_code: str) -> bool:
        """
        Check if user can grant a specific privilege to others.
        
        Rules:
        - SUPERADMIN can grant any privilege
        - ADMIN can grant non-system privileges (not those requiring SUPERADMIN)
        - Others cannot grant privileges
        
        Args:
            privilege_code: Privilege to check if grantable
            
        Returns:
            bool: True if user can grant this privilege to others
        """
        if self.role == Roles.SUPERADMIN or self.is_superuser:
            return True
        
        if self.role == Roles.ADMIN:
            # Restrict granting of super-privileges
            restricted = ["CORE_MANAGE"]  # Can expand as needed
            return privilege_code not in restricted
        
        return False
    
    @property
    def is_admin(self) -> bool:
        """Check if user is admin (SUPERADMIN or ADMIN)"""
        return self.role in [Roles.SUPERADMIN, Roles.ADMIN] or self.is_superuser
    
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


class SpecialPrivilege(models.Model):
    """
    User-specific privilege assignment that overrides role defaults.
    
    Allows granting/revoking specific privileges to/from users,
    independent of their assigned role. Useful for temporary elevated access
    or fine-grained permission control.
    
    Example:
    - Teacher normally has GRADING_ENTER only
    - Can grant GRADING_APPROVE for specific marking period
    - Can set expires_at to auto-revoke after deadline
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="special_privileges",
        help_text="User who holds this privilege"
    )
    code = models.CharField(
        max_length=50,
        help_text="Privilege code (e.g., GRADING_APPROVE, TRANSACTION_DELETE)"
    )
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_privileges_set",
        help_text="User who granted this privilege"
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Privilege automatically revoked after this date (optional)"
    )
    notes = models.TextField(
        blank=True,
        help_text="Reason/notes for granting (e.g., 'Temporary grading approval for Q3')"
    )
    
    class Meta:
        db_table = "user_special_privilege"
        verbose_name = "Special Privilege"
        verbose_name_plural = "Special Privileges"
        # Per-tenant unique constraint (tenant context handled by django-tenants)
        constraints = [
            models.UniqueConstraint(
                fields=["user", "code"],
                name="user_uniq_special_privilege",
            )
        ]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["code"]),
            models.Index(fields=["expires_at"]),
            models.Index(fields=["granted_at"]),
        ]
        ordering = ["-granted_at"]
    
    def __str__(self):
        return f"{self.user.email} - {self.code}"


class RoleDefaultPrivilege(models.Model):
    """
    Maps default privileges for each role.
    
    Defines what privileges a user should have by default when assigned
    a specific role in a tenant. Used for:
    - Initial privilege setup when user joins school
    - Populating user's effective privilege list
    - Determining what role grants what access
    
    Example rows:
    - role=TEACHER, privilege=GRADING_ENTER
    - role=TEACHER, privilege=GRADING_MANAGE (view only)
    - role=ADMIN, privilege=CORE_MANAGE
    - etc.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(
        max_length=20,
        choices=Roles.choices(),
        help_text="Role this privilege applies to"
    )
    privilege_code = models.CharField(
        max_length=50,
        help_text="Privilege code (e.g., STUDENTS_MANAGE)"
    )
    applies_to_account_types = models.JSONField(
        default=list,
        blank=True,
        help_text="Account types this applies to (e.g., ['staff', 'student']). Empty = all types."
    )
    notes = models.TextField(
        blank=True,
        help_text="Description of why this privilege is granted to this role"
    )
    
    class Meta:
        db_table = "user_role_default_privilege"
        verbose_name = "Role Default Privilege"
        verbose_name_plural = "Role Default Privileges"
        # Global unique constraint (applies to all tenants)
        constraints = [
            models.UniqueConstraint(
                fields=["role", "privilege_code"],
                name="user_uniq_role_privilege",
            )
        ]
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["privilege_code"]),
        ]
        ordering = ["role", "privilege_code"]
    
    def __str__(self):
        return f"{self.role.upper()} → {self.privilege_code}"

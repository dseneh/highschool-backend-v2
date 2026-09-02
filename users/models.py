"""
User models for django-tenant-users
User model with UserProfile for multi-tenant user management
"""

import uuid
from django.db import models
from django.contrib.auth.models import Group, Permission
from tenant_users.tenants.models import UserProfile
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
    """Global user identity. Tenant authorization is stored in tenant RBAC."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    photo = models.ImageField(upload_to="users", null=True, blank=True)
    last_password_updated = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    profile_updated_at = models.DateTimeField(null=True, blank=True)
    profile_updated_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="profile_updates_made",
    )
    is_default_password = models.BooleanField(default=False)
    is_platform_superuser = models.BooleanField(
        default=False,
        help_text="Platform-wide administration flag. Tenant authorization uses RBAC memberships.",
    )

    # Security state. security_version is embedded in newly-issued JWTs and can
    # be incremented to invalidate every previously issued access token.
    security_version = models.PositiveBigIntegerField(default=1)
    mfa_enabled = models.BooleanField(default=False)
    mfa_required = models.BooleanField(default=False)
    mfa_secret_envelope = models.JSONField(null=True, blank=True, editable=False)
    mfa_confirmed_at = models.DateTimeField(null=True, blank=True)
    mfa_recovery_code_hashes = models.JSONField(default=list, blank=True, editable=False)

    groups = models.ManyToManyField(Group, blank=True, related_name='school_users')
    user_permissions = models.ManyToManyField(Permission, blank=True, related_name='school_users')

    class Meta:
        db_table = "user"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.email or self.username or self.id_number or str(self.id)

    @property
    def is_admin(self) -> bool:
        return bool(self.is_platform_superuser)

    @property
    def is_staff_user(self) -> bool:
        return self.account_type == UserAccountType.STAFF

    @property
    def is_student_user(self) -> bool:
        return self.account_type == UserAccountType.STUDENT

    @property
    def is_parent_user(self) -> bool:
        return self.account_type == UserAccountType.PARENT

    def get_student(self):
        if not self.is_student_user:
            return None
        try:
            from students.models import Student
            return Student.objects.get(user_account_id_number=self.id_number)
        except Exception:
            return None

    def get_staff(self):
        if not self.is_staff_user:
            return None
        try:
            from staff.models import Staff
            return Staff.objects.get(user_account_id_number=self.id_number)
        except Exception:
            return None

    def get_children(self):
        if not self.is_parent_user:
            return None
        try:
            from students.models import Student, StudentGuardian
            student_ids = StudentGuardian.objects.filter(email=self.email).values_list('student_id', flat=True)
            return Student.objects.filter(id__in=student_ids)
        except Exception:
            return None

    def get_guardian_records(self):
        if not self.is_parent_user:
            return None
        try:
            from students.models import StudentGuardian
            return StudentGuardian.objects.filter(email=self.email)
        except Exception:
            return None

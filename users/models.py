"""
User models for django-tenant-users.

User is the single public-schema identity. Persona, employment, platform access,
and tenant authorization are intentionally separate concerns.
"""

import uuid
from django.db import models
from django.contrib.auth.models import Group, Permission
from tenant_users.tenants.models import UserProfile
from common.status import UserAccountType, UserAccountScope, PersonStatus
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
    """Single global identity that may have multiple tenant/domain personas."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True, null=True, blank=True, help_text="Optional username for login")
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=10, choices=[("male", "Male"), ("female", "Female")], default="male")
    id_number = models.CharField(max_length=50, unique=True)
    account_type = models.CharField(
        max_length=20,
        choices=UserAccountType.choices(),
        default=UserAccountType.OTHER,
        help_text="Primary/default persona only. Do not use this field as an authorization grant.",
    )
    account_scope = models.CharField(
        max_length=32,
        choices=UserAccountScope.choices(),
        default=UserAccountScope.TENANT,
        help_text="Workspace eligibility boundary. Actual authorization still requires role assignments/memberships.",
    )
    status = models.CharField(max_length=20, choices=PersonStatus.choices(), default=PersonStatus.ACTIVE)
    photo = models.ImageField(upload_to="users", null=True, blank=True)
    last_password_updated = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    profile_updated_at = models.DateTimeField(null=True, blank=True)
    profile_updated_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="profile_updates_made"
    )
    is_default_password = models.BooleanField(default=False)
    is_platform_superuser = models.BooleanField(
        default=False,
        help_text="Explicit platform-wide superuser override; independent of persona and account scope.",
    )
    groups = models.ManyToManyField(Group, blank=True, related_name="school_users")
    user_permissions = models.ManyToManyField(Permission, blank=True, related_name="school_users")

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

    @property
    def allows_platform_access(self) -> bool:
        return self.account_scope in {
            UserAccountScope.PLATFORM,
            UserAccountScope.PLATFORM_AND_TENANT,
        }

    @property
    def allows_tenant_access(self) -> bool:
        return self.account_scope in {
            UserAccountScope.TENANT,
            UserAccountScope.PLATFORM_AND_TENANT,
        }

    # Relationship resolution intentionally does not depend on primary account_type.
    # A single identity may simultaneously be staff, student, guardian, and platform staff.
    def get_student(self):
        try:
            from students.models import Student
            return Student.objects.filter(user_account_id_number=self.id_number).first()
        except (ImportError, AttributeError):
            return None

    def get_staff(self):
        try:
            from staff.models import Staff
            return Staff.objects.filter(user_account_id_number=self.id_number).first()
        except (ImportError, AttributeError):
            return None

    def get_children(self):
        try:
            from students.models import Student, StudentGuardian
            student_ids = StudentGuardian.objects.filter(email=self.email).values_list("student_id", flat=True)
            return Student.objects.filter(id__in=student_ids)
        except (ImportError, AttributeError):
            return None

    def get_guardian_records(self):
        try:
            from students.models import StudentGuardian
            return StudentGuardian.objects.filter(email=self.email)
        except (ImportError, AttributeError):
            return None


class PlatformEmployee(models.Model):
    """Employment relationship between a User and the EzySchool platform company."""

    class EmploymentStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        TERMINATED = "terminated", "Terminated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name="platform_employment")
    employee_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    position = models.CharField(max_length=150, blank=True, default="")
    department = models.CharField(max_length=150, blank=True, default="")
    status = models.CharField(max_length=20, choices=EmploymentStatus.choices, default=EmploymentStatus.ACTIVE)
    hire_date = models.DateField(null=True, blank=True)
    termination_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "platform_employee"
        ordering = ("user__last_name", "user__first_name")

    def __str__(self):
        return f"{self.user} ({self.position or 'Platform employee'})"

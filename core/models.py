"""
Core models for multi-tenant application
Tenant model serves as the Tenant model for django-tenants and django-tenant-users

Reference: 
- https://django-tenants.readthedocs.io/en/latest/install.html
- https://django-tenant-users.readthedocs.io/en/latest/pages/installation.html
"""

import uuid
import random
import json
import os
from django.db import models
from django.contrib.postgres.fields import JSONField
from django_tenants.models import DomainMixin
from tenant_users.tenants.models import TenantBase
from core.validators import ValidateImageFile
from common.status import SchoolFundingType, SchoolType


def generate_unique_id_number():
    """
    Generate a unique sequential ID number for tenants starting from 01001.
    Format: 01001, 01002, 01003, etc.
    """
    from django.db import models
    # Get the highest existing id_number
    max_id = Tenant.objects.aggregate(
        max_id=models.Max('id_number')
    )['max_id']
    
    if max_id:
        try:
            # Increment the highest ID
            next_id = int(max_id) + 1
        except (ValueError, TypeError):
            # If conversion fails, start from 01001
            next_id = 1001
    else:
        # First tenant, start from 01001
        next_id = 1001
    
    return str(next_id).zfill(5)  # Pad with zeros to make it 5 digits (01001)


def tenant_logo_upload_path(instance, filename):
    """
    Generate tenant-specific upload path for logo.
    Path: tenants/{schema_name}/logo/{filename}
    """
    ext = os.path.splitext(filename)[1]
    new_filename = f"logo{ext}"
    return f"tenants/{instance.schema_name}/logo/{new_filename}"


class Tenant(TenantBase):
    """
    Tenant model for multi-tenant application.
    Each tenant gets its own PostgreSQL schema for data isolation.
    Contains complete tenant profile information.
    """
    # Override id to use UUID
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Core Identity Fields
    id_number = models.CharField(
        max_length=10, 
        unique=True, 
        default=generate_unique_id_number,
        help_text="Unique identifier for the tenant"
    )
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=50, blank=True, null=True)
    funding_type = models.CharField(
        max_length=100, 
        choices=SchoolFundingType.choices(), 
        default=SchoolFundingType.PRIVATE,
        help_text="Funding type: private, public, charter, etc."
    )
    school_type = models.CharField(
        max_length=100, 
        choices=SchoolType.choices(), 
        default=SchoolType.PRIMARY,
        help_text="School type: primary, secondary, tertiary, etc."
    )
    slogan = models.CharField(max_length=250, blank=True, null=True, help_text="School motto/slogan")
    emis_number = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        help_text="Education Management Information System number"
    )
    description = models.TextField(blank=True, null=True, help_text="Detailed description of the tenant")
    date_est = models.DateField(blank=True, null=True, help_text="Date established")
    
    # Address Fields
    address = models.CharField(max_length=250, blank=True, null=True, help_text="Street address")
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    
    # Contact Fields
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    
    # Status and Configuration
    status = models.CharField(
        max_length=20,
        choices=[
            ("active", "Active"),
            ("on_hold", "On Hold"),
            ("closed", "Closed"),
            ("inactive", "Inactive"),
            ("deleted", "Deleted"),
        ],
        default="active",
        help_text="Tenant status: active, on_hold, closed, inactive, deleted"
    )
    active = models.BooleanField(
        default=True, 
        help_text="Controls whether the workspace is operational. This is independent of lifecycle status."
    )
    maintenance_mode = models.BooleanField(
        default=False,
        help_text="When enabled, tenant workspace operations are paused except for allowed auth/status checks."
    )
    login_access_policy = models.CharField(
        max_length=32,
        choices=[
            ("all_users", "All Users"),
            ("tenant_admin_only", "Tenant Admin Only"),
            ("disabled", "Disabled"),
        ],
        default="all_users",
        help_text="Controls who can sign in to this tenant workspace."
    )
    disabled_access_allow_tenant_admins = models.BooleanField(
        default=True,
        help_text="When workspace access is disabled, tenant admins can still access explicitly allowed pages."
    )
    disabled_access_allowed_paths = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tenant page path prefixes allowed while workspace is disabled (for approved users/admins)."
    )
    disabled_access_allowed_users = models.JSONField(
        default=list,
        blank=True,
        help_text="List of user identifiers (id_number/username/email) allowed on disabled workspace override paths."
    )

    # SaaS billing (Stripe) — public schema fields
    complimentary_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Pilot/partner grace: full access without Stripe billing until this datetime (UTC).",
    )
    complimentary_note = models.TextField(
        blank=True,
        default="",
        help_text="Internal note for complimentary access (e.g. pilot partner thank-you period).",
    )
    stripe_customer_id = models.CharField(max_length=255, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=255, blank=True, default="")
    subscription_status = models.CharField(max_length=32, blank=True, default="")
    billing_interval = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="Stripe subscription interval: month or year.",
    )
    current_period_end = models.DateTimeField(null=True, blank=True)
    past_due_since = models.DateTimeField(null=True, blank=True)
    enabled_addons = models.JSONField(
        default=list,
        blank=True,
        help_text='Active paid add-ons, e.g. ["payroll", "sms"].',
    )
    promotion_code_redeemed = models.CharField(max_length=64, blank=True, default="")
    billing_enrollment_count = models.PositiveIntegerField(default=0)
    billing_employee_count = models.PositiveIntegerField(default=0)
    
    # Logo and Branding
    logo = models.ImageField(
        upload_to=tenant_logo_upload_path,
        null=True,
        blank=True,
        validators=[ValidateImageFile],
        help_text="Tenant logo stored in tenant-specific folder: tenants/{schema_name}/logo/"
    )
    logo_shape = models.CharField(
        max_length=100,
        choices=[("square", "Square"), ("landscape", "Landscape")],
        default="square",
        help_text="Shape of the logo: Square (1:1) or Landscape (2:1 width:height)"
    )
    theme_color = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        help_text="Brand/theme color (hex code)"
    )
    
    # Theme Configuration - JSON field for comprehensive theming
    theme_config = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="Comprehensive theme configuration including colors, typography, spacing, shadows, etc."
    )
    
    # Automatically create schema when tenant is created
    auto_create_schema = True
    # Don't auto-drop schema on delete (safety)
    auto_drop_schema = False
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'tenant'
        verbose_name = "Tenant"
        verbose_name_plural = "Tenants"
        ordering = ["name"]
    
    def __str__(self):
        return self.name
    
    @property
    def is_operational(self):
        return self.active and self.status == "active" and not self.maintenance_mode


class Domain(DomainMixin):
    """
    Domain model for tenant routing.
    Used by django-tenants to identify the tenant based on the request's hostname.
    For header-based routing, this is optional but recommended for compatibility.
    """
    pass
    
    class Meta:
        db_table = 'domain'
        verbose_name = "Domain"
        verbose_name_plural = "Domains"


class PlatformBanner(models.Model):
    """Cross-tenant banner created by platform superadmins (e.g. system
    maintenance windows, billing reminders to school admins, etc.).

    Lives in the public schema so a single banner can target users across
    multiple tenant workspaces. Per-user dismissal state is tracked in
    :class:`PlatformBannerDismissal` (also in the public schema).
    """

    VARIANT_INFO = "info"
    VARIANT_WARNING = "warning"
    VARIANT_ERROR = "error"
    VARIANT_SUCCESS = "success"
    VARIANT_CHOICES = [
        (VARIANT_INFO, "Info"),
        (VARIANT_WARNING, "Warning"),
        (VARIANT_ERROR, "Error"),
        (VARIANT_SUCCESS, "Success"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    action_url = models.CharField(max_length=500, blank=True, default="")

    variant = models.CharField(
        max_length=16, choices=VARIANT_CHOICES, default=VARIANT_INFO
    )
    dismissible = models.BooleanField(default=True)
    starts_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the banner becomes visible. Null = visible immediately.",
    )
    ends_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the banner stops showing. Null = no auto-expiration.",
    )

    # ---- Targeting ----
    # Empty target_tenants = ALL tenants. Otherwise restrict to listed schemas.
    target_tenants = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tenant schema_names to target. Empty = all tenants.",
    )
    # Empty target_roles = ALL roles. Otherwise restrict to e.g. ["admin"].
    target_roles = models.JSONField(
        default=list,
        blank=True,
        help_text='List of role names to target, e.g. ["admin"]. Empty = all roles.',
    )

    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_platform_banners",
    )

    class Meta:
        db_table = "platform_banner"
        verbose_name = "Platform Banner"
        verbose_name_plural = "Platform Banners"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["active", "ends_at"]),
        ]

    def __str__(self):
        return self.title


class PlatformBannerDismissal(models.Model):
    """Per-user dismissal record for a :class:`PlatformBanner`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    banner = models.ForeignKey(
        PlatformBanner,
        on_delete=models.CASCADE,
        related_name="dismissals",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="platform_banner_dismissals",
    )
    dismissed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform_banner_dismissal"
        constraints = [
            models.UniqueConstraint(
                fields=["banner", "user"],
                name="uniq_platform_banner_dismissal",
            )
        ]
        indexes = [
            models.Index(fields=["user", "banner"]),
        ]


class SignupRequest(models.Model):
    """
    Pre-tenant signup request submitted via the public marketing form.
    Stored in the public schema. Used by the admin team to track
    prospective school customers before workspace provisioning.
    """
    STATUS_PENDING   = "pending"
    STATUS_CONTACTED = "contacted"
    STATUS_ONBOARDED = "onboarded"
    STATUS_DECLINED  = "declined"

    STATUS_CHOICES = [
        (STATUS_PENDING,   "Pending"),
        (STATUS_CONTACTED, "Contacted"),
        (STATUS_ONBOARDED, "Onboarded"),
        (STATUS_DECLINED,  "Declined"),
    ]

    # Contact info
    first_name     = models.CharField(max_length=100)
    last_name      = models.CharField(max_length=100)
    email          = models.EmailField()
    phone          = models.CharField(max_length=30, blank=True)

    # School info
    school_name    = models.CharField(max_length=255)
    role_title     = models.CharField(max_length=100)
    country        = models.CharField(max_length=100)
    students_count = models.CharField(max_length=50)

    # Preferences (optional)
    workspace_slug = models.CharField(max_length=30, blank=True)
    plan           = models.CharField(max_length=50, blank=True)
    notes          = models.TextField(blank=True)

    # CRM status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'signup_request'
        verbose_name = "Signup Request"
        verbose_name_plural = "Signup Requests"
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} – {self.school_name} ({self.status})"

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
        help_text="Quick boolean flag for active status (status='active' = active=True)"
    )
    
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
    
    def save(self, *args, **kwargs):
        """Override save to sync active with status."""
        # Sync active with status field
        self.active = (self.status == "active")
        super().save(*args, **kwargs)


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

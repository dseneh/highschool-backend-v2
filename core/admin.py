"""
Admin configuration for core models
"""

from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import Domain, Feature, SignupRequest, Tenant, TenantFeatureEntitlement



@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "short_name", "schema_name", "active", "created_at")
    list_filter = ("active", "created_at")
    search_fields = ("name", "short_name", "schema_name")


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("domain", "tenant__name")


@admin.register(SignupRequest)
class SignupRequestAdmin(admin.ModelAdmin):
    list_display  = ("first_name", "last_name", "email", "school_name", "country", "plan", "status", "submitted_at")
    list_filter   = ("status", "country", "submitted_at")
    search_fields = ("first_name", "last_name", "email", "school_name")
    list_editable = ("status",)
    readonly_fields = ("submitted_at",)
    ordering = ("-submitted_at",)


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "category", "is_purchasable", "is_active")
    list_filter = ("is_active", "is_purchasable", "category")
    search_fields = ("key", "name")


@admin.register(TenantFeatureEntitlement)
class TenantFeatureEntitlementAdmin(admin.ModelAdmin):
    list_display = ("tenant", "feature", "status", "locally_enabled", "cancel_at_period_end")
    list_filter = ("status", "source", "locally_enabled", "cancel_at_period_end")
    search_fields = ("tenant__name", "feature__key")

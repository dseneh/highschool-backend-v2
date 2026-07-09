"""
Admin configuration for core models
"""

from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import Tenant, Domain, SignupRequest



@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "short_name",
        "schema_name",
        "active",
        "complimentary_until",
        "subscription_status",
        "created_at",
    )
    list_filter = ("active", "subscription_status", "created_at")
    search_fields = ("name", "short_name", "schema_name", "stripe_customer_id")
    fieldsets = (
        (None, {"fields": ("name", "short_name", "schema_name", "owner", "active", "status")}),
        (
            "Billing",
            {
                "fields": (
                    "complimentary_until",
                    "complimentary_note",
                    "enabled_addons",
                    "stripe_customer_id",
                    "stripe_subscription_id",
                    "subscription_status",
                    "billing_interval",
                    "current_period_end",
                    "past_due_since",
                    "billing_enrollment_count",
                    "billing_employee_count",
                    "promotion_code_redeemed",
                ),
            },
        ),
    )


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

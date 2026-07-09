from django.contrib import admin

from billing.models import BillingSeat


@admin.register(BillingSeat)
class BillingSeatAdmin(admin.ModelAdmin):
    list_display = (
        "tenant",
        "enrollment_id",
        "academic_year_id",
        "activated_at",
        "voided_at",
        "locked_at",
    )
    list_filter = ("voided_at",)
    search_fields = ("tenant__schema_name", "tenant__name", "enrollment_id")

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Attendance,
    Enrollment,
    Student,
    StudentContact,
    StudentConcession,
    StudentEnrollmentBill,
    StudentGuardian,
    StudentPaymentSummary,
)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = [
        "id_number",
        "first_name",
        "last_name",
        "email",
        "status",
    ]
    search_fields = ["id_number", "first_name", "last_name", "email"]
    list_filter = ["status", "gender"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["student", "section", "status"]
    search_fields = ["student__first_name", "student__last_name", "student__id_number"]
    list_filter = ["status"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ["enrollment", "date", "status"]
    search_fields = [
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "enrollment__student__id_number",
    ]
    list_filter = ["status", "date"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "date"


# @admin.register(GradeBook)
# class GradeBookAdmin(admin.ModelAdmin):
#     list_display = ["enrollment", "subject", "grade", "marking_period"]
#     search_fields = [
#         "enrollment__student__first_name",
#         "enrollment__student__last_name",
#         "subject__name",
#     ]
#     list_filter = ["marking_period", "subject"]
#     readonly_fields = ["created_at", "updated_at"]


@admin.register(StudentEnrollmentBill)
class StudentEnrollmentBillAdmin(admin.ModelAdmin):
    list_display = ["enrollment", "name", "amount", "type"]
    search_fields = [
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "enrollment__student__id_number",
        "name",
    ]
    list_filter = ["type"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(StudentConcession)
class StudentConcessionAdmin(admin.ModelAdmin):
    list_display = [
        "student",
        "academic_year",
        "target",
        "concession_type",
        "value",
        "amount",
        "active",
    ]
    search_fields = [
        "student__first_name",
        "student__last_name",
        "student__id_number",
        "academic_year__name",
    ]
    list_filter = ["academic_year", "target", "concession_type", "active"]
    readonly_fields = ["amount", "created_at", "updated_at"]


@admin.register(StudentPaymentSummary)
class StudentPaymentSummaryAdmin(admin.ModelAdmin):
    list_display = [
        "enrollment",
        "academic_year",
        "total_paid",
        "last_calculated_at",
        "recalculate_link",
    ]
    search_fields = [
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "enrollment__student__id_number",
        "academic_year__name",
    ]
    list_filter = ["academic_year", "last_calculated_at"]
    readonly_fields = [
        "payment_plan",
        "payment_status",
        "total_paid",
        "last_calculated_at",
        "created_at",
        "updated_at",
    ]
    actions = ["recalculate_selected_summaries"]

    def recalculate_link(self, obj):
        """Display a link to recalculate this summary"""
        return format_html(
            '<a href="/admin/students/studentpaymentsummary/{}/recalculate/">Recalculate</a>',
            obj.id,
        )

    recalculate_link.short_description = "Actions"

    def recalculate_selected_summaries(self, request, queryset):
        """Admin action to recalculate selected payment summaries"""
        from finance.utils import calculate_student_payment_summary

        count = 0
        errors = 0
        for summary in queryset:
            try:
                calculate_student_payment_summary(
                    summary.enrollment, summary.academic_year
                )
                count += 1
            except Exception as e:
                errors += 1
                self.message_user(
                    request,
                    f"Error recalculating summary for {summary.enrollment}: {e}",
                    level="ERROR",
                )

        if count > 0:
            self.message_user(
                request,
                f"Successfully recalculated {count} payment summary(s).",
                level="SUCCESS",
            )
        if errors > 0:
            self.message_user(
                request,
                f"Failed to recalculate {errors} payment summary(s).",
                level="WARNING",
            )

    recalculate_selected_summaries.short_description = "Recalculate selected payment summaries"


@admin.register(StudentContact)
class StudentContactAdmin(admin.ModelAdmin):
    list_display = ["full_name", "student", "relationship", "phone_number", "is_emergency", "is_primary"]
    search_fields = ["first_name", "last_name", "student__first_name", "student__last_name", "student__id_number"]
    list_filter = ["relationship", "is_emergency", "is_primary"]


@admin.register(StudentGuardian)
class StudentGuardianAdmin(admin.ModelAdmin):
    list_display = ["full_name", "student", "relationship", "phone_number", "is_primary"]
    search_fields = ["first_name", "last_name", "student__first_name", "student__last_name", "student__id_number"]
    list_filter = ["relationship", "is_primary"]

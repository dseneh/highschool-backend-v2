from django.contrib import admin

from .models import (
    EmployeeCompensation,
    EmployeePayrollItem,
    EmployeeWard,
    PayrollCatalogItem,
    PayrollCatalogItemRule,
    PayrollDeductionInstallment,
    PayrollDeductionSchedule,
    PayrollEmployeeItem,
    PayrollLineItem,
    PayrollPayslipTemplate,
    PayrollRunRecord,
    SalaryAdvance,
    StaffWardSponsorship,
    StaffWardSponsorshipPolicy,
    StaffWardSponsorshipStudent,
    PayrollTableView,
)


class PayrollCatalogItemRuleInline(admin.TabularInline):
    model = PayrollCatalogItemRule
    extra = 0


@admin.register(PayrollCatalogItem)
class PayrollCatalogItemAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "line_type", "priority", "is_active")
    search_fields = ("name", "code")
    list_filter = ("line_type", "is_active")
    inlines = [PayrollCatalogItemRuleInline]


@admin.register(PayrollCatalogItemRule)
class PayrollCatalogItemRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "payroll_item", "calculation_type", "priority", "is_active")
    search_fields = ("name", "payroll_item__name")
    list_filter = ("calculation_type", "is_active")


@admin.register(EmployeePayrollItem)
class EmployeePayrollItemAdmin(admin.ModelAdmin):
    list_display = ("employee", "payroll_item", "calculation_type", "is_active")
    search_fields = ("employee__first_name", "employee__last_name", "payroll_item__name")


class PayrollLineItemInline(admin.TabularInline):
    model = PayrollLineItem
    extra = 0
    readonly_fields = ("line_type", "name", "amount")


@admin.register(PayrollEmployeeItem)
class PayrollEmployeeItemAdmin(admin.ModelAdmin):
    list_display = ("payroll", "employee", "gross_pay", "net_pay", "payment_status")
    inlines = [PayrollLineItemInline]


@admin.register(PayrollRunRecord)
class PayrollRunRecordAdmin(admin.ModelAdmin):
    list_display = ("payroll_number", "status", "pay_period_start", "pay_period_end", "net_pay_total")
    search_fields = ("payroll_number",)
    list_filter = ("status",)


@admin.register(PayrollTableView)
class PayrollTableViewAdmin(admin.ModelAdmin):
    list_display = ("name", "is_default", "applies_to", "is_system")


@admin.register(PayrollPayslipTemplate)
class PayrollPayslipTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "is_default", "is_system")


@admin.register(StaffWardSponsorshipPolicy)
class StaffWardSponsorshipPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "coverage_type", "coverage_value", "effective_from", "effective_to")
    list_filter = ("is_active", "coverage_type")
    search_fields = ("name",)


@admin.register(EmployeeWard)
class EmployeeWardAdmin(admin.ModelAdmin):
    list_display = ("employee", "student", "relationship_type", "is_verified", "is_active")
    list_filter = ("relationship_type", "is_verified", "is_active")
    search_fields = ("employee__id_number", "student__id_number", "employee__first_name", "student__first_name")


@admin.register(StaffWardSponsorship)
class StaffWardSponsorshipAdmin(admin.ModelAdmin):
    list_display = ("employee", "academic_year", "policy", "status", "employee_contribution_amount", "payroll_recovery_amount")
    list_filter = ("status", "academic_year")
    search_fields = ("employee__id_number", "employee__first_name", "employee__last_name")


@admin.register(StaffWardSponsorshipStudent)
class StaffWardSponsorshipStudentAdmin(admin.ModelAdmin):
    list_display = ("sponsorship", "student", "eligible_fee_total", "school_covered_amount", "employee_responsibility_amount")
    search_fields = ("student__id_number", "student__first_name", "student__last_name")


@admin.register(SalaryAdvance)
class SalaryAdvanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "request_date", "approved_amount", "remaining_balance", "status")
    list_filter = ("status",)
    search_fields = ("employee__id_number", "employee__first_name", "employee__last_name")


@admin.register(PayrollDeductionSchedule)
class PayrollDeductionScheduleAdmin(admin.ModelAdmin):
    list_display = ("employee", "source_type", "source_id", "total_amount", "remaining_amount", "status")
    list_filter = ("source_type", "status")
    search_fields = ("employee__id_number", "source_id")


@admin.register(PayrollDeductionInstallment)
class PayrollDeductionInstallmentAdmin(admin.ModelAdmin):
    list_display = ("deduction_schedule", "payroll_period", "scheduled_amount", "actual_amount", "status")
    list_filter = ("status",)

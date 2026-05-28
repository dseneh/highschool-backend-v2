from django.contrib import admin

from .models import (
    EmployeeCompensation,
    EmployeePayrollItem,
    PayrollCatalogItem,
    PayrollCatalogItemRule,
    PayrollEmployeeItem,
    PayrollLineItem,
    PayrollPayslipTemplate,
    PayrollRunRecord,
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

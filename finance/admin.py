from django.contrib import admin

from .models import (
    BankAccount,
    Currency,
    GeneralFeeList,
    PaymentInstallment,
    PaymentMethod,
    SectionFee,
    Transaction,
    TransactionType,
)


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ["name", "number", "bank_number", "balance"]
    search_fields = ["name", "number", "bank_number"]
    list_filter = []
    readonly_fields = ["created_at", "updated_at", "balance"]


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ["name", "is_editable"]
    search_fields = ["name"]
    list_filter = ["is_editable"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "symbol"]
    search_fields = ["name", "code"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(GeneralFeeList)
class GeneralFeeListAdmin(admin.ModelAdmin):
    list_display = ["name", "amount"]
    search_fields = ["name"]
    list_filter = []
    readonly_fields = ["created_at", "updated_at"]


@admin.register(SectionFee)
class SectionFeeAdmin(admin.ModelAdmin):
    list_display = ["section", "general_fee", "amount"]
    search_fields = ["section__name", "general_fee__name"]
    list_filter = []
    readonly_fields = ["created_at", "updated_at"]


@admin.register(TransactionType)
class TransactionTypeAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]
    list_filter = []
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ["id", "type", "amount", "status", "account", "date"]
    search_fields = ["id", "type__name", "description"]
    list_filter = ["status", "type", "account", "date"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "date"


@admin.register(PaymentInstallment)
class PaymentInstallmentAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "academic_year",
        "value",
        "due_date",
        "sequence",
        "active",
    ]
    search_fields = ["name", "description"]
    list_filter = ["academic_year", "active"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["academic_year", "sequence", "due_date"]



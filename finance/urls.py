from django.urls import include, path
from rest_framework.routers import DefaultRouter

from finance.views import (
    BankAccountDetailView,
    BankAccountListView,
    CurrencyDetailView,
    CurrencyListView,
    GeneralFeeDetailView,
    GeneralFeeListView,
    PaymentInstallmentDetailView,
    PaymentInstallmentListView,
    PaymentMethodDetailView,
    PaymentMethodListView,
    SectionFeeDetailView,
    SectionFeeListView,
    StudentPaymentStatusListView,
    TransactionTypeDetailView,
    TransactionTypeListView,
    TransactionViewSet,
    get_billing_summary,
)

router = DefaultRouter()
router.register(
    r"transactions",
    TransactionViewSet,
    basename="school-transactions",
)

urlpatterns = [
    path("", include(router.urls)),
    # Bank Account endpoints
    path(
        "bankaccounts/",
        BankAccountListView.as_view(),
        name="bank-account-list",
    ),
    path(
        "bankaccounts/<str:id>/",
        BankAccountDetailView.as_view(),
        name="bank-account-detail",
    ),
    # General Fee endpoints
    path(
        "general-fees/",
        GeneralFeeListView.as_view(),
        name="general-fee-list",
    ),
    path(
        "general-fees/<str:id>/",
        GeneralFeeDetailView.as_view(),
        name="general-fee-detail",
    ),
    # Section Fee endpoints
    path(
        "sections/<str:section_id>/section-fees/",
        SectionFeeListView.as_view(),
        name="section-fee-list",
    ),
    path(
        "section-fees/<str:id>/",
        SectionFeeDetailView.as_view(),
        name="section-fee-detail",
    ),
    # Transaction Type endpoints
    path(
        "transaction-types/",
        TransactionTypeListView.as_view(),
        name="transaction-type-list",
    ),
    path(
        "transaction-types/<str:pk>/",
        TransactionTypeDetailView.as_view(),
        name="transaction-type-detail",
    ),
    path(
        "payment-methods/",
        PaymentMethodListView.as_view(),
        name="school-payment-method-list",
    ),
    path(
        "payment-methods/<str:pk>/",
        PaymentMethodDetailView.as_view(),
        name="payment-method-detail",
    ),
    # Add endpoint for currency
    path(
        "currencies/",
        CurrencyListView.as_view(),
        name="school-currency-list",
    ),
    path("currencies/<str:pk>/", CurrencyDetailView.as_view(), name="currency-detail"),
    # Payment Installment endpoints
    path(
        "academic-years/<str:academic_year_id>/installments/",
        PaymentInstallmentListView.as_view(),
        name="payment-installment-list",
    ),
    path(
        "installments/<str:pk>/",
        PaymentInstallmentDetailView.as_view(),
        name="payment-installment-detail",
    ),
    # Student Payment Status endpoints
    path(
        "students/payment-status/",
        StudentPaymentStatusListView.as_view(),
        name="student-payment-status-list",
    ),
    # Billing Summary endpoint for dashboard
    path(
        "billing/summary/",
        get_billing_summary,
        name="billing-summary",
    ),
]

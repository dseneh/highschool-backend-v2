from django.urls import path

from billing.views import (
    BillingCheckoutView,
    BillingPortalView,
    BillingSummaryView,
    StripeWebhookView,
)

urlpatterns = [
    path("billing/summary/", BillingSummaryView.as_view(), name="billing-summary"),
    path("billing/checkout/", BillingCheckoutView.as_view(), name="billing-checkout"),
    path("billing/portal/", BillingPortalView.as_view(), name="billing-portal"),
    path("billing/webhooks/stripe/", StripeWebhookView.as_view(), name="stripe-webhook"),
]

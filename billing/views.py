from __future__ import annotations

import logging

import stripe
from django.conf import settings
from django.db import connection
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.constants import (
    PRICE_LOOKUP_PAYROLL_ANNUAL,
    PRICE_LOOKUP_PAYROLL_MONTHLY,
    PRICE_LOOKUP_SMS_METERED,
    PRICE_LOOKUP_STANDARD_ANNUAL,
    PRICE_LOOKUP_STANDARD_MONTHLY,
)
from billing.permissions import IsTenantAdmin, user_is_tenant_admin
from billing.services.access import billing_blocks_writes
from billing.services.seats import billable_seat_count
from billing.services.state import billing_summary_dict
from billing.services.stripe_client import (
    ensure_stripe_customer,
    get_stripe_client,
    retrieve_price_by_lookup_key,
    stripe_configured,
)
from billing.services.stripe_sync import find_tenant_for_stripe_object, sync_tenant_from_subscription
from core.models import Tenant

logger = logging.getLogger(__name__)


def _resolve_tenant(request) -> Tenant | None:
    schema = connection.schema_name
    if schema == "public":
        return None
    return Tenant.objects.filter(schema_name=schema).first()


class BillingSummaryView(APIView):
    permission_classes = [IsTenantAdmin]

    def get(self, request):
        tenant = _resolve_tenant(request)
        if not tenant:
            return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(billing_summary_dict(tenant, for_admin=True))


class BillingCheckoutView(APIView):
    permission_classes = [IsTenantAdmin]

    def post(self, request):
        if not stripe_configured():
            return Response({"detail": "Stripe is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        tenant = _resolve_tenant(request)
        if not tenant:
            return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

        interval = (request.data.get("interval") or "year").lower()
        include_payroll = bool(request.data.get("include_payroll", False))
        include_sms = bool(request.data.get("include_sms", False))
        academic_year_id = request.data.get("academic_year_id")

        if interval not in {"year", "month"}:
            return Response({"detail": "interval must be 'year' or 'month'."}, status=status.HTTP_400_BAD_REQUEST)

        standard_lookup = (
            PRICE_LOOKUP_STANDARD_ANNUAL if interval == "year" else PRICE_LOOKUP_STANDARD_MONTHLY
        )
        payroll_lookup = (
            PRICE_LOOKUP_PAYROLL_ANNUAL if interval == "year" else PRICE_LOOKUP_PAYROLL_MONTHLY
        )

        try:
            standard_price = retrieve_price_by_lookup_key(standard_lookup)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        seat_count = tenant.billing_enrollment_count or 0
        if academic_year_id:
            seat_count = max(seat_count, billable_seat_count(tenant, academic_year_id))
        seat_count = max(seat_count, 1)

        minimum = (
            settings.BILLING_ANNUAL_MINIMUM_USD
            if interval == "year"
            else settings.BILLING_MONTHLY_MINIMUM_USD
        )
        unit_amount = (standard_price.get("unit_amount") or 0) / 100
        if unit_amount > 0:
            import math
            seat_count = max(seat_count, math.ceil(minimum / unit_amount))

        line_items = [{"price": standard_price["id"], "quantity": seat_count}]

        if include_payroll:
            try:
                payroll_price = retrieve_price_by_lookup_key(payroll_lookup)
                employee_count = max(int(request.data.get("employee_count") or tenant.billing_employee_count or 1), 1)
                line_items.append({"price": payroll_price["id"], "quantity": employee_count})
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if include_sms:
            try:
                sms_price = retrieve_price_by_lookup_key(PRICE_LOOKUP_SMS_METERED)
                line_items.append({"price": sms_price["id"]})
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        customer_id = ensure_stripe_customer(tenant)
        client = get_stripe_client()

        success_url = request.data.get("success_url") or settings.STRIPE_CHECKOUT_SUCCESS_URL
        cancel_url = request.data.get("cancel_url") or settings.STRIPE_CHECKOUT_CANCEL_URL
        if not success_url or not cancel_url:
            return Response(
                {"detail": "Checkout success/cancel URLs are not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        session = client.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=line_items,
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,
            client_reference_id=str(tenant.id),
            subscription_data={
                "metadata": {
                    "tenant_id": str(tenant.id),
                    "schema_name": tenant.schema_name,
                },
            },
            metadata={
                "tenant_id": str(tenant.id),
                "schema_name": tenant.schema_name,
            },
        )
        return Response({"url": session["url"], "session_id": session["id"]})


class BillingPortalView(APIView):
    permission_classes = [IsTenantAdmin]

    def post(self, request):
        if not stripe_configured():
            return Response({"detail": "Stripe is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        tenant = _resolve_tenant(request)
        if not tenant:
            return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

        if not tenant.stripe_customer_id:
            return Response({"detail": "No Stripe customer for this workspace."}, status=status.HTTP_400_BAD_REQUEST)

        return_url = request.data.get("return_url") or settings.STRIPE_PORTAL_RETURN_URL
        if not return_url:
            return Response({"detail": "Portal return URL is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        client = get_stripe_client()
        session = client.billing_portal.Session.create(
            customer=tenant.stripe_customer_id,
            return_url=return_url,
        )
        return Response({"url": session["url"]})


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not stripe_configured():
            return HttpResponse(status=503)

        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError:
            return HttpResponse(status=400)

        event_type = event.get("type", "")
        data_object = event.get("data", {}).get("object", {})

        try:
            if event_type.startswith("customer.subscription."):
                self._handle_subscription_event(data_object)
            elif event_type == "invoice.paid":
                self._handle_invoice_paid(data_object)
            elif event_type == "invoice.payment_failed":
                self._handle_invoice_payment_failed(data_object)
            elif event_type == "checkout.session.completed":
                self._handle_checkout_completed(data_object)
        except Exception:
            logger.exception("Stripe webhook handler failed for %s", event_type)

        return HttpResponse(status=200)

    def _handle_subscription_event(self, subscription: dict):
        tenant = find_tenant_for_stripe_object(subscription)
        if not tenant:
            return
        client = get_stripe_client()
        full = client.Subscription.retrieve(
            subscription["id"],
            expand=["items.data.price.product"],
        )
        sync_tenant_from_subscription(tenant, full)

    def _handle_invoice_paid(self, invoice: dict):
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return
        tenant = find_tenant_for_stripe_object(invoice)
        if not tenant:
            tenant = Tenant.objects.filter(stripe_subscription_id=subscription_id).first()
        if not tenant:
            return
        client = get_stripe_client()
        full = client.Subscription.retrieve(
            subscription_id,
            expand=["items.data.price.product"],
        )
        sync_tenant_from_subscription(tenant, full)

    def _handle_invoice_payment_failed(self, invoice: dict):
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return
        tenant = Tenant.objects.filter(stripe_subscription_id=subscription_id).first()
        if not tenant:
            tenant = find_tenant_for_stripe_object(invoice)
        if not tenant:
            return
        client = get_stripe_client()
        full = client.Subscription.retrieve(
            subscription_id,
            expand=["items.data.price.product"],
        )
        sync_tenant_from_subscription(tenant, full)

    def _handle_checkout_completed(self, session: dict):
        tenant = find_tenant_for_stripe_object(session)
        if not tenant:
            ref = session.get("client_reference_id")
            if ref:
                tenant = Tenant.objects.filter(id=ref).first()
        if not tenant:
            return

        customer_id = session.get("customer")
        if customer_id and not tenant.stripe_customer_id:
            tenant.stripe_customer_id = customer_id
            tenant.save(update_fields=["stripe_customer_id", "updated_at"])

        subscription_id = session.get("subscription")
        if subscription_id:
            client = get_stripe_client()
            full = client.Subscription.retrieve(
                subscription_id,
                expand=["items.data.price.product"],
            )
            sync_tenant_from_subscription(tenant, full)


class BillingAccessMixin:
    """DRF mixin: block writes when subscription is in grace/expired state."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        tenant = _resolve_tenant(request)
        if not tenant:
            return
        if billing_blocks_writes(tenant, is_tenant_admin=user_is_tenant_admin(request.user)):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                detail="Workspace billing requires attention. Changes are temporarily disabled.",
                code="billing_read_only",
            )

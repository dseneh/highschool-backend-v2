from __future__ import annotations

import stripe
from django.conf import settings


def get_stripe_client():
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def stripe_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def retrieve_price_by_lookup_key(lookup_key: str):
    client = get_stripe_client()
    prices = client.Price.list(lookup_keys=[lookup_key], active=True, limit=1)
    data = prices.get("data") or []
    if not data:
        raise ValueError(f"Stripe price not found for lookup_key={lookup_key}")
    return data[0]


def ensure_stripe_customer(tenant):
    if tenant.stripe_customer_id:
        return tenant.stripe_customer_id

    client = get_stripe_client()
    customer = client.Customer.create(
        name=tenant.name,
        email=tenant.email or None,
        metadata={
            "tenant_id": str(tenant.id),
            "schema_name": tenant.schema_name,
        },
    )
    tenant.stripe_customer_id = customer["id"]
    tenant.save(update_fields=["stripe_customer_id", "updated_at"])
    return customer["id"]

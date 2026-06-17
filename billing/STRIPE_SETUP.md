# Stripe Billing Setup for EzySchool

Configure these objects in the [Stripe Dashboard](https://dashboard.stripe.com) (Test mode first).

## 1. Products and metadata

| Product | metadata.type | metadata.addon_key |
|---------|---------------|-------------------|
| EzySchool Standard | `base` | *(empty)* |
| EzySchool Payroll | `addon` | `payroll` |
| EzySchool SMS | `addon` | `sms` |

## 2. Prices (lookup keys)

| lookup_key | Amount | Interval | Quantity |
|------------|--------|----------|----------|
| `ezyschool_standard_annual` | $4.50 | year | licensed (students) |
| `ezyschool_standard_monthly` | $0.42 | month | licensed (students) |
| `addon_payroll_annual` | $4.00 | year | licensed (employees) |
| `addon_payroll_monthly` | $0.34 | month | licensed (employees) |
| `addon_sms_metered` | $0.04 | — | metered (SMS) |

Create a **Billing Meter** named `sms_sent` and link it to `addon_sms_metered`.

## 3. Webhook endpoint

**URL:** `https://<your-api-host>/api/v1/billing/webhooks/stripe/`

**Events:**
- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`

Copy the signing secret to `STRIPE_WEBHOOK_SECRET`.

## 4. Environment variables

```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_CHECKOUT_SUCCESS_URL=https://{workspace}.ezyschool.app/settings/billing?checkout=success
STRIPE_CHECKOUT_CANCEL_URL=https://{workspace}.ezyschool.app/settings/billing?checkout=cancel
STRIPE_PORTAL_RETURN_URL=https://{workspace}.ezyschool.app/settings/billing
```

For local dev, use Stripe CLI:

```bash
stripe listen --forward-to localhost:8000/api/v1/billing/webhooks/stripe/
```

## 5. Customer Portal

Enable in Stripe Dashboard → Settings → Billing → Customer portal:
- Update payment methods
- View invoices
- Cancel subscription (optional)

## 6. Promotion codes (optional)

Create coupons (e.g. `LAUNCH20` — 20% off once) and promotion codes. Checkout has `allow_promotion_codes=True`.

## 7. Pilot / complimentary schools

In Django admin → Tenants, set **Complimentary access until** and optional **Complimentary note**. No Stripe subscription required until that date.

Optionally set **Enabled add-ons** to `["payroll", "sms"]` as JSON for full feature access during the thank-you period.

## 8. Install dependency

```bash
pip install stripe>=11.0.0
python manage.py migrate core billing
```

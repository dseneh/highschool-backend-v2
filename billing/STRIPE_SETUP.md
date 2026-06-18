# Stripe Billing Setup for EzySchool

Configure these objects in the [Stripe Dashboard](https://dashboard.stripe.com) (Test mode first).

## 1. Products and metadata

| Product | metadata.type | metadata.addon_key |
|---------|---------------|-------------------|
| EzySchool Standard | `base` | *(empty)* |
| EzySchool Payroll | `addon` | `payroll` |

*(SMS add-on is planned for a future release — skip for initial rollout.)*

## 2. Prices (lookup keys)

| lookup_key | Amount | Interval | Quantity |
|------------|--------|----------|----------|
| `ezyschool_standard_annual` | $4.50 | year | licensed (students) |
| `ezyschool_standard_monthly` | $0.42 | month | licensed (students) |
| `addon_payroll_annual` | $4.00 | year | licensed (employees) |
| `addon_payroll_monthly` | $0.34 | month | licensed (employees) |

*(SMS metered price `addon_sms_metered` — add when SMS notifications ship.)*

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

Only **platform-wide** keys are required. Checkout/portal return URLs are built **per tenant** from `FRONTEND_DOMAIN` + the tenant `schema_name` (same helper as password-reset links). You do **not** configure `{workspace}` in env.

```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Used to build https://<schema_name>.<your-domain>/settings?tab=billing
FRONTEND_DOMAIN=https://ezyschool.app
FRONTEND_USE_SUBDOMAIN=true
```

**How redirect URLs are resolved**

1. **Preferred:** the UI sends `success_url`, `cancel_url`, and `return_url` using `window.location.origin` (already includes the tenant subdomain).
2. **Fallback:** the API builds them server-side, e.g. `https://ldtc.ezyschool.app/settings?tab=billing&checkout=success`.
3. **Security:** if a client sends a URL whose host does not match that tenant's workspace, the server ignores it and uses the built-in default.

Optional legacy overrides (single-tenant dev only — not needed in production):

```env
# STRIPE_CHECKOUT_SUCCESS_URL=
# STRIPE_CHECKOUT_CANCEL_URL=
# STRIPE_PORTAL_RETURN_URL=
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

## 8. Billing reminder emails

Schedule daily (cron or Celery beat):

```bash
python manage.py send_billing_reminders
```

Emails tenant admins at **30, 14, 7, and 3 days** before complimentary access or subscription renewal ends, plus overdue payment notices.

Optional Celery task: `billing.send_billing_reminders`

## 9. Install dependency

```bash
pip install stripe>=11.0.0
python manage.py migrate core billing
```

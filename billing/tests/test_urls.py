from django.test import SimpleTestCase, override_settings

from billing.services.urls import (
    build_billing_checkout_urls,
    build_billing_settings_url,
    resolve_checkout_urls,
)


class TenantStub:
    schema_name = "ldtc"


@override_settings(
    FRONTEND_DOMAIN="https://ezyschool.app",
    FRONTEND_USE_SUBDOMAIN=True,
    FRONTEND_DEV_MODE=False,
)
class BillingUrlTests(SimpleTestCase):
    def test_build_billing_settings_url(self):
        url = build_billing_settings_url(TenantStub())
        self.assertEqual(url, "https://ldtc.ezyschool.app/settings?tab=billing")

    def test_build_checkout_urls(self):
        success, cancel = build_billing_checkout_urls(TenantStub())
        self.assertIn("checkout=success", success)
        self.assertIn("checkout=cancel", cancel)
        self.assertTrue(success.startswith("https://ldtc.ezyschool.app/"))

    def test_rejects_foreign_redirect(self):
        tenant = TenantStub()
        success, cancel = resolve_checkout_urls(
            tenant,
            success_url="https://evil.example/settings?tab=billing&checkout=success",
            cancel_url="https://evil.example/settings?tab=billing&checkout=cancel",
        )
        self.assertIn("ldtc.ezyschool.app", success)
        self.assertIn("ldtc.ezyschool.app", cancel)

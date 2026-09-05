import hashlib
import hmac

from django.core.cache import cache
from django.test import SimpleTestCase

from common.payment_security import (
    build_idempotency_key,
    claim_webhook_event,
    timestamp_is_fresh,
    verify_hmac_sha256,
)


class PaymentSecurityTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()

    def test_hmac_signature_verification(self):
        payload = b'{"event":"paid"}'
        secret = "provider-secret"
        signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        self.assertTrue(verify_hmac_sha256(payload, signature, secret).valid)
        self.assertFalse(verify_hmac_sha256(payload, "bad", secret).valid)

    def test_webhook_event_can_only_be_claimed_once(self):
        self.assertTrue(claim_webhook_event("provider", "evt-123"))
        self.assertFalse(claim_webhook_event("provider", "evt-123"))

    def test_idempotency_key_is_deterministic(self):
        first = build_idempotency_key("tenant-a", "student-1", "invoice-2", "10.00")
        second = build_idempotency_key("tenant-a", "student-1", "invoice-2", "10.00")
        other = build_idempotency_key("tenant-a", "student-1", "invoice-2", "11.00")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_timestamp_freshness_rejects_old_events(self):
        import time
        now = int(time.time())
        self.assertTrue(timestamp_is_fresh(now, tolerance_seconds=60))
        self.assertFalse(timestamp_is_fresh(now - 3600, tolerance_seconds=60))

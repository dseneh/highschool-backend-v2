from datetime import timedelta

from django.conf import settings
from django.test import SimpleTestCase

from users.sso_serializers import SsoBootstrapSerializer
from users.sso_views import SSO_SESSION_LIFETIME


class RememberedSessionLifetimeTests(SimpleTestCase):
    def test_refresh_and_sso_lifetimes_support_thirty_day_remember_me(self):
        self.assertEqual(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"], timedelta(days=30))
        self.assertEqual(SSO_SESSION_LIFETIME, timedelta(days=30))

        serializer = SsoBootstrapSerializer(data={"ttl_seconds": 30 * 86400})
        self.assertTrue(serializer.is_valid(), serializer.errors)

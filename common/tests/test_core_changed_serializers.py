from unittest.mock import Mock

from django.test import SimpleTestCase

from core.models import PlatformBanner, SignupRequest, Tenant
from core.platform_banner_serializers import PlatformBannerSerializer
from core.serializers import SignupRequestAdminSerializer, TenantSerializer


class CoreChangedSerializerTests(SimpleTestCase):
    def assert_noop_update_skips_save(self, serializer_class, instance, data):
        instance.save = Mock()
        serializer = serializer_class(instance, data=data, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        self.assertIs(serializer.save(), instance)
        instance.save.assert_not_called()

    def test_tenant_noop_update_skips_save(self):
        tenant = Tenant(
            id_number="SCH00001",
            name="Demo School",
            short_name="Demo",
            schema_name="demo",
        )
        self.assert_noop_update_skips_save(
            TenantSerializer,
            tenant,
            {"name": "Demo School"},
        )

    def test_platform_banner_noop_update_skips_save(self):
        banner = PlatformBanner(title="Maintenance", active=True)
        self.assert_noop_update_skips_save(
            PlatformBannerSerializer,
            banner,
            {"title": "Maintenance", "active": True},
        )

    def test_signup_request_noop_update_skips_save(self):
        signup_request = SignupRequest(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            school_name="Demo School",
        )
        self.assert_noop_update_skips_save(
            SignupRequestAdminSerializer,
            signup_request,
            {"first_name": "Ada", "email": "ada@example.com"},
        )

"""CI-specific test runner helpers."""

from django.test.runner import DiscoverRunner
from django_tenants.test.cases import TenantTestCase


class CIFastTenantTestRunner(DiscoverRunner):
    """Avoid rebuilding the already-created public schema per test class.

    ``TEST.MIGRATE = False`` creates the public test schema directly from the
    current model state. ``TenantTestCase.sync_shared()`` would otherwise try
    to apply real migrations over those existing tables for every tenant test
    class. Tenant creation and tenant-schema migrations remain unchanged.
    """

    def run_suite(self, suite, **kwargs):
        original_sync_shared = TenantTestCase.__dict__["sync_shared"]
        TenantTestCase.sync_shared = classmethod(lambda cls: None)
        try:
            return super().run_suite(suite, **kwargs)
        finally:
            TenantTestCase.sync_shared = original_sync_shared

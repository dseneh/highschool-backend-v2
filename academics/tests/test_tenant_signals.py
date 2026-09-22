from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from academics.signals import setup_tenant_defaults
from core.models import Tenant


class TenantDefaultsSignalTests(SimpleTestCase):
    def test_initial_plan_uses_direct_update_without_recursive_tenant_save(self):
        tenant = SimpleNamespace(
            pk="tenant-1",
            schema_name="new-school",
            name="New School",
            onboarding_plan={},
        )
        plan = {"current_step": "school_profile", "steps": {}}

        with patch(
            "defaults.services.build_initial_plan",
            return_value=plan,
        ), patch.object(Tenant.objects, "filter") as tenant_filter:
            setup_tenant_defaults(
                sender=Tenant,
                instance=tenant,
                created=True,
            )

        tenant_filter.assert_called_once_with(pk=tenant.pk)
        tenant_filter.return_value.update.assert_called_once_with(
            onboarding_plan=plan
        )
        self.assertEqual(tenant.onboarding_plan, plan)

    def test_existing_plan_is_not_rewritten(self):
        tenant = SimpleNamespace(
            pk="tenant-1",
            schema_name="new-school",
            name="New School",
            onboarding_plan={"steps": {"school_profile": {}}},
        )

        with patch.object(Tenant.objects, "filter") as tenant_filter:
            setup_tenant_defaults(
                sender=Tenant,
                instance=tenant,
                created=True,
            )

        tenant_filter.assert_not_called()

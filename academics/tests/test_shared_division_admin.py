from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from academics.views.division import DivisionListView
from common.status import Roles
from users.models import User


class SharedDivisionAdminPermissionTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Shared Division Permission School"
        tenant.id_number = "SDP001"
        tenant.owner, _ = User.objects.get_or_create(
            email="shared-division-admin@example.com",
            defaults={
                "username": "shared-division-admin",
                "id_number": "SHARED-DIVISION-ADMIN-001",
                "role": Roles.ADMIN,
            },
        )

    def test_tenant_admin_cannot_create_shared_divisions(self):
        request = APIRequestFactory().post(
            "/divisions/",
            {"name": "Unauthorized Division"},
            format="json",
        )
        force_authenticate(request, user=self.tenant.owner)

        response = DivisionListView.as_view()(request)

        self.assertEqual(response.status_code, 403)

    def test_superadmin_is_authorized_to_manage_shared_divisions(self):
        superadmin, _ = User.objects.get_or_create(
            email="shared-division-superadmin@example.com",
            defaults={
                "username": "shared-division-superadmin",
                "id_number": "SHARED-DIVISION-SUPERADMIN-001",
                "role": Roles.SUPERADMIN,
            },
        )
        request = APIRequestFactory().post(
            "/divisions/",
            {"name": ""},
            format="json",
        )
        force_authenticate(request, user=superadmin)

        response = DivisionListView.as_view()(request)

        self.assertEqual(response.status_code, 400)
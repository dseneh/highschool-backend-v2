from types import SimpleNamespace

from django.test import SimpleTestCase

from authorization.cache import (
    CachedAuthorizationBundle,
    CachedMembership,
    CachedRolePermissions,
    CachedRolePointer,
)
from authorization.runtime import _context_from_bundle, resolve_authorization_context
from users.access_policies import BaseSchoolAccessPolicy


class SuperadminAuthorizationRuntimeTests(SimpleTestCase):
    def test_platform_superadmin_is_unrestricted_without_role_grants(self):
        user = SimpleNamespace(
            pk="user-1",
            is_authenticated=True,
            is_active=True,
            is_platform_superuser=True,
        )

        context = resolve_authorization_context(user, schema_name="school_a")

        self.assertTrue(context.unrestricted)
        self.assertEqual(context.permission_scope("grades.enter"), "all")

    def test_school_access_policies_bypass_rules_for_platform_superadmin(self):
        user = SimpleNamespace(
            is_authenticated=True,
            is_platform_superuser=True,
        )
        request = SimpleNamespace(user=user)

        self.assertTrue(BaseSchoolAccessPolicy().has_permission(request, object()))
        self.assertTrue(
            BaseSchoolAccessPolicy().has_object_permission(
                request,
                object(),
                object(),
            )
        )

    def test_cached_superadmin_role_is_unrestricted_without_role_grants(self):
        bundle = CachedAuthorizationBundle(
            membership=CachedMembership(
                exists=True,
                membership_id="membership-1",
                role_id="role-1",
                active=True,
            ),
            role=CachedRolePointer(
                role_id="role-1",
                permission_version=1,
                active=True,
                system_key="superadmin",
            ),
            role_permissions=CachedRolePermissions(
                role_id="role-1",
                permission_version=1,
                permissions={},
            ),
        )

        context = _context_from_bundle("school_a", "user-1", bundle)

        self.assertTrue(context.unrestricted)
        self.assertEqual(context.permission_scope("grades.enter"), "all")
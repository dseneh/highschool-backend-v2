from unittest.mock import Mock, patch

import msgspec
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from authorization.cache import (
    AuthorizationCache,
    CachedMembership,
    CachedRolePermissions,
    CachedRolePointer,
)


@override_settings(USE_REDIS=False)
class AuthorizationCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_cache_keys_are_isolated_by_tenant_schema(self):
        first = AuthorizationCache.membership_key("school_a", "user-1")
        second = AuthorizationCache.membership_key("school_b", "user-1")

        self.assertNotEqual(first, second)
        self.assertIn("{school_a}", first)
        self.assertIn("{school_b}", second)

    def test_round_trips_typed_membership_and_role_payloads(self):
        membership = CachedMembership(
            exists=True,
            membership_id="membership-1",
            membership_version=2,
            role_id="role-1",
            active=True,
        )
        role = CachedRolePointer(
            role_id="role-1",
            permission_version=4,
            active=True,
        )
        permissions = CachedRolePermissions(
            role_id="role-1",
            permission_version=4,
            permissions={"students.view": "assigned"},
        )

        AuthorizationCache.set_authorization(
            "school_a",
            "user-1",
            membership,
            role,
            permissions,
        )
        bundle = AuthorizationCache.get_bundle("school_a", "user-1")

        self.assertEqual(bundle.membership, membership)
        self.assertEqual(bundle.role, role)
        self.assertEqual(bundle.role_permissions, permissions)

    def test_negative_membership_is_cached_without_role_lookup(self):
        membership = CachedMembership(exists=False)
        AuthorizationCache.set_authorization(
            "school_a",
            "user-1",
            membership,
        )

        bundle = AuthorizationCache.get_bundle("school_a", "user-1")

        self.assertFalse(bundle.membership.exists)
        self.assertIsNone(bundle.role)

    def test_malformed_payload_fails_closed_and_is_removed(self):
        key = AuthorizationCache.membership_key("school_a", "user-1")
        cache.set(key, b"not-json", 60)

        self.assertIsNone(AuthorizationCache.get_bundle("school_a", "user-1"))
        self.assertIsNone(cache.get(key))

    @override_settings(USE_REDIS=True)
    def test_redis_bundle_uses_one_script_round_trip(self):
        membership = CachedMembership(
            exists=True,
            membership_id="membership-1",
            membership_version=1,
            role_id="role-1",
            active=True,
        )
        role = CachedRolePointer(
            role_id="role-1",
            permission_version=1,
            active=True,
        )
        permissions = CachedRolePermissions(
            role_id="role-1",
            permission_version=1,
            permissions={"students.view": "all"},
        )
        redis_connection = Mock()
        redis_connection.eval.return_value = [
            msgspec.json.encode(membership),
            msgspec.json.encode(role),
            msgspec.msgpack.encode(permissions),
        ]

        with patch.object(
            AuthorizationCache,
            "_redis_connection",
            return_value=redis_connection,
        ):
            bundle = AuthorizationCache.get_bundle("school_a", "user-1")

        self.assertEqual(bundle.role_permissions.permissions, {"students.view": "all"})
        redis_connection.eval.assert_called_once()

    @override_settings(USE_REDIS=True)
    def test_redis_invalidation_retries_transient_failures(self):
        redis_connection = Mock()
        redis_connection.delete.side_effect = [
            RuntimeError("temporary"),
            RuntimeError("temporary"),
            1,
        ]

        with patch.object(
            AuthorizationCache,
            "_redis_connection",
            return_value=redis_connection,
        ):
            AuthorizationCache.invalidate_role("school_a", "role-1")

        self.assertEqual(redis_connection.delete.call_count, 3)

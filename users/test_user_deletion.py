from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase
from users.viewsets import UserViewSet


class UserDeletionPermissionTests(SimpleTestCase):
    def setUp(self):
        self.view = UserViewSet()
        self.actor = SimpleNamespace(pk="actor")
        self.request = SimpleNamespace(user=self.actor, tenant=SimpleNamespace(schema_name="school_a"))
        self.target = MagicMock(pk="target", is_platform_superuser=False)
        self.target.tenants.filter.return_value.exists.return_value = True
        self.target.tenants.exclude.return_value.exists.return_value = False

    def test_self_deletion_is_always_rejected(self):
        self.assertEqual(self.view._user_deletion_denial(self.request, self.actor, True).status_code, 403)

    @patch("users.viewsets.is_global_superadmin", return_value=False)
    @patch("users.viewsets.UserAccessPolicy.is_role_in", return_value=False)
    def test_non_admin_cannot_force_hard_delete(self, role, platform):
        self.assertEqual(self.view._user_deletion_denial(self.request, self.target, True).status_code, 403)

    @patch("users.viewsets.is_global_superadmin", return_value=False)
    @patch("users.viewsets.UserAccessPolicy.is_role_in", return_value=True)
    def test_tenant_admin_cannot_delete_account_in_another_school(self, role, platform):
        self.target.tenants.filter.return_value.exists.return_value = False
        self.assertEqual(self.view._user_deletion_denial(self.request, self.target, True).status_code, 403)

    @patch("users.viewsets.is_global_superadmin", return_value=False)
    @patch("users.viewsets.UserAccessPolicy.is_role_in", return_value=True)
    def test_shared_accounts_require_platform_admin_for_soft_and_hard_deletion(self, role, platform):
        self.target.tenants.exclude.return_value.exists.return_value = True
        for hard in [False, True]:
            self.assertEqual(self.view._user_deletion_denial(self.request, self.target, hard).status_code, 409)

    @patch("users.viewsets.is_global_superadmin", return_value=True)
    def test_platform_admin_can_delete_other_accounts(self, platform):
        self.assertIsNone(self.view._user_deletion_denial(self.request, self.target, True))

    @patch("users.models.ParentStudentLink.objects.filter")
    @patch("users.models.ParentSchoolRegistration.objects.filter")
    @patch("users.viewsets.is_global_superadmin", return_value=False)
    @patch("users.viewsets.UserAccessPolicy.is_role_in", return_value=True)
    def test_tenant_admin_can_delete_exclusively_local_account(self, role, platform, registrations, links):
        registrations.return_value.exclude.return_value.exists.return_value = False
        links.return_value.exclude.return_value.exists.return_value = False
        self.assertIsNone(self.view._user_deletion_denial(self.request, self.target, True))
        links.return_value.exclude.return_value.exists.return_value = True
        self.assertEqual(self.view._user_deletion_denial(self.request, self.target, True).status_code, 409)


class UserDeletionLockTests(SimpleTestCase):
    @patch("users.viewsets.transaction.set_rollback")
    @patch("users.viewsets.transaction.atomic")
    def test_read_only_probes_release_savepoint_locks_even_when_matching(self, atomic, rollback):
        for exists in [False, True]:
            self.assertEqual(UserViewSet._reference_exists(lambda: exists), exists)
        self.assertEqual(rollback.call_count, 2)
        rollback.assert_called_with(True)

    @patch("users.viewsets.connection")
    @patch.object(UserViewSet, "_reference_exists", return_value=False)
    def test_catalog_cleanup_does_not_write_to_empty_tables(self, probe, cursor):
        cursor.ops.quote_name.side_effect = lambda value: f'"{value}"'
        cursor = cursor.cursor
        cursor.return_value.__enter__.return_value.fetchall.return_value = [
            ("school_a", "audit", "actor_id", False),
            ("school_b", "audit", "actor_id", False),
        ]
        UserViewSet._purge_user_refs_via_pg_constraint("target")
        commands = [call.args[0] for call in cursor.return_value.__enter__.return_value.execute.call_args_list]
        self.assertFalse(any(sql.startswith(("DELETE", "UPDATE")) for sql in commands))
        self.assertEqual(probe.call_count, 2)

    @patch("users.viewsets.connection")
    @patch.object(UserViewSet, "_reference_exists", return_value=True)
    def test_cleanup_only_writes_to_permitted_schemas(self, probe, cursor):
        cursor.ops.quote_name.side_effect = lambda value: f'"{value}"'
        cursor = cursor.cursor
        cursor.return_value.__enter__.return_value.fetchall.return_value = [
            ("school_a", "audit", "actor_id", False),
            ("school_b", "audit", "actor_id", False),
        ]
        UserViewSet._purge_user_refs_via_pg_constraint("target", allowed_schemas={"school_a"})
        commands = [call.args[0] for call in cursor.return_value.__enter__.return_value.execute.call_args_list]
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(sum(sql.startswith("UPDATE") for sql in commands), 1)
        self.assertFalse(any('"school_b"' in sql for sql in commands))

    @patch("users.viewsets.connection")
    @patch.object(UserViewSet, "_reference_exists", side_effect=RuntimeError("lock exhaustion"))
    def test_cleanup_failure_propagates_to_outer_transaction(self, probe, cursor):
        cursor.ops.quote_name.side_effect = lambda value: f'"{value}"'
        cursor = cursor.cursor
        cursor.return_value.__enter__.return_value.fetchall.return_value = [("school_a", "audit", "actor_id", False)]
        with self.assertRaisesRegex(RuntimeError, "lock exhaustion"):
            UserViewSet._purge_user_refs_via_pg_constraint("target")

    @patch("users.viewsets.schema_context")
    @patch("users.viewsets.connection")
    @patch.object(UserViewSet, "_reference_exists", return_value=True)
    def test_disconnected_membership_uses_orm_cascade_in_its_own_school(self, probe, connection_mock, schema):
        from authorization.models import TenantMembership
        connection_mock.ops.quote_name.side_effect = lambda value: f'"{value}"'
        cursor = connection_mock.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("school_a", TenantMembership._meta.db_table, "user_id", True)]
        with patch.object(TenantMembership._base_manager, "filter") as memberships:
            UserViewSet._purge_user_refs_via_pg_constraint("target")
            memberships.assert_called_once_with(user_id="target")
            memberships.return_value.delete.assert_called_once_with()
        schema.assert_called_once_with("school_a")
        self.assertFalse(any(call.args[0].startswith("DELETE") for call in cursor.execute.call_args_list))


class AccountReferenceTests(SimpleTestCase):
    @patch('users.models.User.objects.filter')
    def test_deleted_account_reference_is_not_presented(self, lookup):
        from common.account_link import existing_account_reference
        lookup.return_value.exists.return_value = False
        self.assertIsNone(existing_account_reference('DELETED'))
        lookup.assert_called_once_with(id_number='DELETED')

    @patch('users.models.User.objects.filter')
    def test_existing_inactive_account_reference_is_preserved(self, lookup):
        from common.account_link import existing_account_reference
        lookup.return_value.exists.return_value = True
        self.assertEqual(existing_account_reference('BLOCKED'), 'BLOCKED')

    @patch('users.models.User.objects.filter')
    def test_empty_reference_does_not_query_accounts(self, lookup):
        from common.account_link import existing_account_reference
        self.assertIsNone(existing_account_reference(None))
        lookup.assert_not_called()

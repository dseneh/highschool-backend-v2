from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied, ValidationError
from users.identity_email import linked_account, normalize_email, sync_record_email, require_email_editor


class IdentityEmailTests(SimpleTestCase):
    def test_email_normalization_and_validation(self):
        self.assertEqual(normalize_email(' Parent@Example.com '), 'parent@example.com')
        for value in ['', None, 'not-an-email']:
            with self.assertRaises(ValidationError):
                normalize_email(value)

    @patch('users.models.User.objects.filter')
    def test_unlinked_matching_contact_text_does_not_link_account(self, lookup):
        record = SimpleNamespace(email='same@example.com', id_number='SAME')
        self.assertIsNone(linked_account(record))
        lookup.assert_not_called()

    @patch('users.models.User.objects.filter')
    def test_dangling_account_reference_fails_closed(self, lookup):
        lookup.return_value.first.return_value = None
        with self.assertRaises(ValidationError):
            linked_account(SimpleNamespace(user_account_id_number='MISSING'))

    @patch('users.models.ParentProfile.objects.select_related')
    @patch('users.models.User.objects.filter')
    def test_contradictory_profile_and_account_fail_closed(self, lookup, profiles):
        lookup.return_value.first.return_value = SimpleNamespace(pk='one')
        profiles.return_value.filter.return_value.first.return_value = SimpleNamespace(user_id='two')
        with self.assertRaises(ValidationError):
            linked_account(SimpleNamespace(user_account_id_number='one', parent_profile_id='profile'))

    @patch('users.identity_email.set_account_email')
    @patch('users.identity_email.require_email_editor', side_effect=PermissionDenied())
    @patch('users.identity_email.linked_account')
    def test_contact_permission_alone_cannot_change_login(self, lookup, permission, update):
        lookup.return_value = SimpleNamespace(email='old@example.com')
        with self.assertRaises(PermissionDenied):
            sync_record_email(object(), {'email': 'new@example.com'}, object())
        update.assert_not_called()

    @patch('users.identity_email.set_account_email')
    @patch('users.identity_email.require_email_editor')
    @patch('users.identity_email.linked_account', return_value=None)
    def test_unlinked_contact_remains_school_specific(self, lookup, permission, update):
        data = {'email': 'contact@example.com'}
        sync_record_email(object(), data, object())
        update.assert_not_called()
        permission.assert_not_called()

    @patch('users.tenant_access.is_global_superadmin', return_value=False)
    @patch('users.access_policies.UserAccessPolicy.has_rbac_permission', return_value=False)
    def test_selected_role_requires_account_permission(self, permission, platform):
        with self.assertRaises(PermissionDenied):
            require_email_editor(SimpleNamespace(user=object()), object())

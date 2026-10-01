from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from users.account_setup import validate_parent_identity_references
from users.account_setup_views import SetupVerifySerializer


class ParentIdentityRecoveryTests(SimpleTestCase):
    @patch('users.account_setup.ParentProfile.objects.filter')
    @patch('users.account_setup.User.objects.filter')
    def test_missing_references_do_not_block_verified_setup(self, users, profiles):
        users.return_value.exclude.return_value.exists.return_value = False
        profiles.return_value.exclude.return_value.exists.return_value = False
        account = SimpleNamespace(pk='new-account')
        validate_parent_identity_references([SimpleNamespace(user_account_id_number='deleted-account', parent_profile_id='deleted-profile')], account)
        users.return_value.exclude.assert_called_once_with(pk=account.pk)
        profiles.return_value.exclude.assert_called_once_with(user=account)

    @patch('users.account_setup.ParentProfile.objects.filter')
    @patch('users.account_setup.User.objects.filter')
    def test_existing_different_owner_or_profile_is_rejected(self, users, profiles):
        for owner_exists, profile_exists in [(True, False), (False, True)]:
            users.return_value.exclude.return_value.exists.return_value = owner_exists
            profiles.return_value.exclude.return_value.exists.return_value = profile_exists
            with self.assertRaises(ValidationError):
                validate_parent_identity_references([SimpleNamespace(user_account_id_number='other', parent_profile_id='other')], SimpleNamespace(pk='new'))

    def test_verification_code_requires_six_digits_including_leading_zeroes(self):
        from uuid import uuid4
        for code, valid in [("012345", True), ("12345", False), ("12345678", False), ("abcdef", False)]:
            serializer = SetupVerifySerializer(data={"challenge_id": str(uuid4()), "code": code})
            self.assertEqual(serializer.is_valid(), valid, serializer.errors)

    def test_parent_prefill_excludes_gender_but_preserves_staff_and_student_prefill(self):
        from users.account_setup import setup_source_details
        source = SimpleNamespace(first_name='Alex', gender='female')
        self.assertNotIn('gender', setup_source_details(source, 'parent'))
        for kind in ['staff', 'student']:
            self.assertEqual(setup_source_details(source, kind)['gender'], 'female')

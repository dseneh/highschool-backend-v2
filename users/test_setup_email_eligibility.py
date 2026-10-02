from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from django.core.cache import cache
from rest_framework.exceptions import ValidationError, Throttled
from rest_framework.test import APIRequestFactory
from users.account_setup import require_parent_setup_eligible, reserve_setup_email
from users.account_setup_views import AccountSetupView
from users import global_parent_setup
from api.throttling import SensitiveEndpointRateThrottle


@override_settings(ACCOUNT_SETUP_EMAIL_ENABLED=True)
class SetupEligibilityTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch('users.account_setup.ParentProfile.objects.filter')
    @patch('users.account_setup.User.objects.filter')
    def test_existing_parent_rejected_but_staff_without_parent_profile_allowed(self, users, profiles):
        account = SimpleNamespace(account_type='staff', is_active=True, status='active')
        users.return_value.first.return_value = account
        profiles.return_value.exists.return_value = True
        with self.assertRaisesMessage(ValidationError, 'parent account already exists'):
            require_parent_setup_eligible('staff@example.com')
        profiles.return_value.exists.return_value = False
        require_parent_setup_eligible('staff@example.com')
        account.account_type = 'parent'
        with self.assertRaises(ValidationError):
            require_parent_setup_eligible('staff@example.com')

    @patch('common.email_service.send_notification_email')
    @patch('users.global_parent_setup.AccountSetupChallenge.objects.create')
    @patch('users.global_parent_setup.discover', side_effect=ValidationError('No eligible record'))
    @patch('users.global_parent_setup.require_parent_setup_eligible')
    def test_missing_school_record_sends_no_email_and_creates_no_challenge(self, eligible, discover, create, send):
        with self.assertRaises(ValidationError):
            global_parent_setup.begin(object(), 'parent', ' MISSING@example.com ')
        discover.assert_called_once_with('missing@example.com')
        send.assert_not_called()
        create.assert_not_called()

    @patch('common.email_service.send_notification_email')
    @patch('users.global_parent_setup.discover')
    @patch('users.global_parent_setup.require_parent_setup_eligible', side_effect=ValidationError('Already registered'))
    def test_registered_parent_gets_no_code(self, eligible, discover, send):
        with self.assertRaises(ValidationError):
            global_parent_setup.begin(object(), 'parent', 'parent@example.com')
        discover.assert_not_called()
        send.assert_not_called()

    @patch('users.account_setup.AccountSetupChallenge.objects.filter')
    def test_per_email_cooldown_is_atomic_even_before_challenge_creation(self, challenges):
        challenges.return_value.exists.return_value = False
        reserve_setup_email('parent@example.com')
        with self.assertRaises(Throttled):
            reserve_setup_email('parent@example.com')

    @patch('users.global_parent_setup.begin', return_value=SimpleNamespace(pk='challenge'))
    def test_start_enforces_standard_activation_limit_and_retry_after(self, begin):
        factory = APIRequestFactory()
        rates = {**SensitiveEndpointRateThrottle.THROTTLE_RATES, 'activation': '2/min'}
        responses = []
        with patch.object(SensitiveEndpointRateThrottle, 'THROTTLE_RATES', rates):
            for _ in range(3):
                request = factory.post('/api/v1/auth/account-setup/start/', {'account_type': 'parent', 'email': 'parent@example.com'}, format='json', HTTP_X_TENANT='parent', REMOTE_ADDR='192.0.2.31')
                request.tenant = SimpleNamespace(schema_name='public')
                responses.append(AccountSetupView.as_view(authentication_classes=[])(request, action='start'))
        self.assertEqual([r.status_code for r in responses], [200, 200, 429])
        self.assertIn('Retry-After', responses[-1])
        self.assertEqual(begin.call_count, 2)

    @patch('users.global_parent_setup.begin')
    def test_invalid_email_is_rejected_before_service(self, begin):
        request = APIRequestFactory().post('/api/v1/auth/account-setup/start/', {'account_type': 'parent', 'email': 'invalid'}, format='json', HTTP_X_TENANT='parent')
        request.tenant = SimpleNamespace(schema_name='public')
        response = AccountSetupView.as_view(authentication_classes=[])(request, action='start')
        self.assertEqual(response.status_code, 400)
        begin.assert_not_called()

from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase
from core.models import Tenant
from users.models import OAuthClient, OAuthRedirectURI, User

from django.core.management.base import CommandError
from django.test import SimpleTestCase
from users.management.commands.configure_parent_workspace import admin_callback, parent_callback, school_callback


class ParentCallbackTests(SimpleTestCase):
    def test_admin_callback_uses_the_validated_environment_root(self):
        self.assertEqual(admin_callback("https://parent.myezyschool.com"), "https://admin.myezyschool.com/auth/callback")
        self.assertEqual(admin_callback("https://parent.staging.myezyschool.com"), "https://admin.staging.myezyschool.com/auth/callback")
        self.assertEqual(admin_callback("http://parent.localhost:3001"), "http://admin.localhost:3001/auth/callback")

    def test_admin_callback_rejects_unsafe_origins(self):
        for origin in ["http://parent.example.com", "https://parent.example.com/evil", "https://parent.example.com?next=evil", "https://user:password@parent.example.com"]:
            with self.subTest(origin=origin), self.assertRaises(CommandError):
                admin_callback(origin)

    def test_exact_production_and_local_origins(self):
        self.assertEqual(parent_callback("https://parent.example.com/"), "https://parent.example.com/auth/callback")
        self.assertEqual(parent_callback("http://parent.localhost:3001"), "http://parent.localhost:3001/auth/callback")

    def test_rejects_unsafe_or_non_parent_origins(self):
        for value in ["http://parent.example.com", "https://school.example.com", "https://parent.example.com/evil", "https://parent.example.com?next=evil", "https://user:password@parent.example.com", "https://*.example.com", "https://parent.example.com:bad", "https://parent.example.com#fragment"]:
            with self.subTest(value=value), self.assertRaises(CommandError):
                parent_callback(value)


    def test_school_callbacks_are_exact_and_stay_under_selected_root(self):
        self.assertEqual(school_callback("https://parent.staging.myezyschool.com", "ldtc"), "https://ldtc.staging.myezyschool.com/auth/callback")
        self.assertEqual(school_callback("http://parent.localhost:3001", "school-one"), "http://school-one.localhost:3001/auth/callback")

    def test_school_callback_rejects_reserved_names_and_host_injection(self):
        for slug in ["parent", "public", "auth", "admin", "api", "www", "school.evil.test", "school/evil", "school@evil", "*", "-school", "school-", ""]:
            with self.subTest(slug=slug), self.assertRaises(CommandError):
                school_callback("https://parent.staging.myezyschool.com", slug)




class AdminCallbackRegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if not Tenant.objects.filter(schema_name='public').exists():
            owner = User.objects.create(username='callback-test-owner', email='callback-test@example.test')
            with patch.object(Tenant, 'auto_create_schema', False):
                Tenant.objects.create(schema_name='public', name='Public', owner=owner, active=True, status='active')
        else:
            Tenant.objects.filter(schema_name='public').update(active=True, status='active')

    def configure(self, **kwargs):
        call_command('configure_parent_workspace', origin='https://parent.myezyschool.com', include_admin=True, stdout=StringIO(), **kwargs)

    def test_dry_run_then_idempotent_exact_registration(self):
        self.configure()
        self.assertFalse(OAuthClient.objects.filter(client_id='ezyschool-web').exists())
        self.configure(apply=True)
        self.configure(apply=True)
        client = OAuthClient.objects.get(client_id='ezyschool-web')
        self.assertTrue(client.require_pkce)
        self.assertEqual(set(client.redirect_uris.values_list('redirect_uri', flat=True)), {
            'https://parent.myezyschool.com/auth/callback',
            'https://admin.myezyschool.com/auth/callback',
        })

    def test_disabled_admin_callback_is_not_reactivated(self):
        client = OAuthClient.objects.create(client_id='ezyschool-web', name='Test')
        disabled = OAuthRedirectURI.objects.create(client=client, redirect_uri='https://admin.myezyschool.com/auth/callback', is_active=False)
        with self.assertRaises(CommandError):
            self.configure(apply=True)
        disabled.refresh_from_db()
        self.assertFalse(disabled.is_active)
        self.assertEqual(client.redirect_uris.count(), 1)

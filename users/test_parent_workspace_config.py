from django.core.management.base import CommandError
from django.test import SimpleTestCase
from users.management.commands.configure_parent_workspace import parent_callback


class ParentCallbackTests(SimpleTestCase):
    def test_exact_production_and_local_origins(self):
        self.assertEqual(parent_callback("https://parent.example.com/"), "https://parent.example.com/auth/callback")
        self.assertEqual(parent_callback("http://parent.localhost:3001"), "http://parent.localhost:3001/auth/callback")

    def test_rejects_unsafe_or_non_parent_origins(self):
        for value in ["http://parent.example.com", "https://school.example.com", "https://parent.example.com/evil", "https://parent.example.com?next=evil", "https://user:password@parent.example.com", "https://*.example.com", "https://parent.example.com:bad", "https://parent.example.com#fragment"]:
            with self.subTest(value=value), self.assertRaises(CommandError):
                parent_callback(value)

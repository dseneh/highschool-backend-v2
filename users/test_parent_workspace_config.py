from django.core.management.base import CommandError
from django.test import SimpleTestCase
from users.management.commands.configure_parent_workspace import parent_callback, school_callback


class ParentCallbackTests(SimpleTestCase):
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

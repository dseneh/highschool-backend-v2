from types import SimpleNamespace

from django.test import SimpleTestCase

from accounting.services.bank_rules import _recipient_emails_for_rule


class AccountingRuleRecipientEmailTests(SimpleTestCase):
    def test_recipient_emails_include_only_valid_emails(self):
        recipients = [
            SimpleNamespace(email="valid.one@example.org"),
            SimpleNamespace(email="invalid"),
            SimpleNamespace(email=""),
            SimpleNamespace(email="VALID.ONE@example.org"),
            SimpleNamespace(email="valid.two@example.org"),
        ]
        rule = SimpleNamespace(
            alert_recipients=SimpleNamespace(all=lambda: recipients),
        )

        emails = _recipient_emails_for_rule(rule)

        self.assertEqual(emails, ["valid.one@example.org", "valid.two@example.org"])

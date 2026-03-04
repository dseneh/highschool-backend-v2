"""
Test email template rendering
"""
import os
import sys

import django

# Add the project directory to Python path
sys.path.append("/Users/dewardseneh/workdir/dewx/webapps/highschool/backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")
django.setup()

from django.conf import settings

from users.utils import get_email_context, get_email_message


# Mock user and school objects
class MockSchool:
    def __init__(self):
        self.name = "Greenwood High School"
        self.workspace = "greenwood-high"
        self.address = "123 Education Street, Learning City, LC 12345"


class MockUser:
    def __init__(self):
        self.first_name = "John"
        self.last_name = "Doe"
        self.username = "john.doe"
        self.email = "john.doe@example.com"
        self.school = MockSchool()


def test_email_template():
    print("Testing email template rendering...\n")

    user = MockUser()
    reset_url = "http://localhost:3000/s/greenwood-high/auth/reset-password?uid=MTIz&token=abc123&workspace=greenwood-high"

    try:
        # Test email message generation
        email_data = get_email_message(reset_url, settings, user, user.school)

        print("✅ Email templates rendered successfully!")
        print(f"📧 Subject context: Password Reset Request")
        print(f"👤 User: {email_data['context']['user_name']}")
        print(f"🏫 School: {email_data['context']['school_name']}")
        print(f"⏰ Timeout: {email_data['context']['timeout_hours']} hours")
        print(f"🔗 Reset URL in context: {email_data['context']['reset_url']}")
        print(f"📅 Year: {email_data['context']['current_year']}")

        # Debug: Print first 500 chars of HTML to see what's happening
        print(f"\n🔍 HTML Content Preview:")
        print(email_data["html_message"][:500] + "...")

        # Check if HTML content contains expected elements
        html_content = email_data["html_message"]

        # More specific URL checks
        has_full_url = reset_url in html_content
        has_partial_url = "s/greenwood-high/auth/reset-password" in html_content
        has_href = f'href="{reset_url}"' in html_content
        has_any_url = "http://localhost:3000" in html_content

        print(f"\n🔍 URL Debug:")
        print(f"  Full URL present: {has_full_url}")
        print(f"  Partial URL present: {has_partial_url}")
        print(f"  HREF with URL: {has_href}")
        print(f"  Any localhost URL: {has_any_url}")

        # Find all href attributes
        import re

        href_matches = re.findall(r'href="([^"]*)"', html_content)
        print(f"  Found HREFs: {href_matches}")

        checks = [
            ("user name", user.first_name in html_content),
            ("school name", user.school.name in html_content),
            ("reset URL", has_any_url),
            ("button styling", "cta-button" in html_content),
            ("responsive design", "@media" in html_content),
        ]

        print("\n📋 HTML Template Checks:")
        for check_name, passed in checks:
            status = "✅" if passed else "❌"
            print(f"  {status} {check_name}")

        # Check text version
        text_content = email_data["text_message"]
        text_has_url = reset_url in text_content
        text_has_partial = "localhost:3000" in text_content

        print(f"\n📝 Text Template Debug:")
        print(f"  Text version length: {len(text_content)} characters")
        print(f"  Contains full reset URL: {text_has_url}")
        print(f"  Contains localhost: {text_has_partial}")

        # Print first 200 chars of text version
        print(f"  Text preview: {text_content[:200]}...")

    except Exception as e:
        print(f"❌ Error testing email template: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_email_template()

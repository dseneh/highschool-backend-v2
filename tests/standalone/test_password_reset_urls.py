"""
Test script to verify password reset URL building
"""
import os
import sys

import django

# Add the project directory to Python path
sys.path.append("/Users/dewardseneh/workdir/dewx/webapps/highschool/backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")
django.setup()

from django.conf import settings

from users.utils import build_frontend_url, build_password_reset_url


def test_url_building():
    print("Testing URL building functions...\n")

    # Test data
    test_cases = [
        {"workspace": "demo-school", "uid": "MTIz", "token": "abc123-def456"},
        {"workspace": None, "uid": "MTIz", "token": "abc123-def456"},
    ]

    for dev_mode in [True, False]:
        print(f"{'='*50}")
        print(f"Testing with DEV_MODE = {dev_mode}")
        print(f"{'='*50}")

        # Temporarily override settings for testing
        original_dev_mode = getattr(settings, "FRONTEND_DEV_MODE", True)
        settings.FRONTEND_DEV_MODE = dev_mode

        for case in test_cases:
            workspace = case["workspace"]
            uid = case["uid"]
            token = case["token"]

            print(f"\nWorkspace: {workspace or 'None'}")

            # Test base URL building
            base_url = build_frontend_url(workspace)
            print(f"Base URL: {base_url}")

            # Test password reset URL building
            reset_url = build_password_reset_url(workspace, uid, token)
            print(f"Reset URL: {reset_url}")

        # Restore original setting
        settings.FRONTEND_DEV_MODE = original_dev_mode
        print()


if __name__ == "__main__":
    test_url_building()

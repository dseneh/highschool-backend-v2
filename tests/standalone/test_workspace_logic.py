"""
Test the autodef test_workspace_scenarios():
    print("Testing automatic workspace detection scenarios...\n")tic workspace detection for password reset
"""

import os
import sys

import django

# Add the project root to the Python path
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, project_root)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")
django.setup()

from users.utils import build_password_reset_url


def test_workspace_scenarios():
    print("Testing automatic workspace detection scenarios...\n")

    test_cases = [
        {
            "name": "School User with Workspace",
            "workspace": "greenwood-high",
            "expected_contains": "greenwood-high",
        },
        {
            "name": "Admin User with admin workspace",
            "workspace": "admin",
            "expected_contains": "admin",
        },
        {
            "name": "User without workspace (fallback)",
            "workspace": None,
            "expected_contains": None,
        },
        {"name": "Empty workspace", "workspace": "", "expected_contains": None},
    ]

    for i, case in enumerate(test_cases, 1):
        print(f"Test Case {i}: {case['name']}")
        print(f"Workspace: {case['workspace'] or 'None'}")

        url = build_password_reset_url(case["workspace"], "test-uid", "test-token")

        print(f"Generated URL: {url}")
        print("---")


if __name__ == "__main__":
    test_workspace_scenarios()
import os
import sys

import django

# Add the project directory to Python path
sys.path.append("/Users/dewardseneh/workdir/dewx/webapps/highschool/backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")
django.setup()

from users.utils import build_password_reset_url


def test_workspace_scenarios():
    print("Testing automatic workspace detection scenarios...\n")

    test_cases = [
        {
            "name": "School User with Workspace",
            "workspace": "greenwood-high",
            "uid": "MTIz",
            "token": "abc123",
        },
        {
            "name": "Admin User with admin workspace",
            "workspace": "admin",
            "uid": "NDU2",
            "token": "def456",
        },
        {
            "name": "User without workspace (fallback)",
            "workspace": None,
            "uid": "Nzg5",
            "token": "ghi789",
        },
        {"name": "Empty workspace", "workspace": "", "uid": "MDAx", "token": "jkl012"},
    ]

    for case in test_cases:
        print(f"Test Case: {case['name']}")
        print(f"Workspace: {case['workspace'] or 'None'}")

        reset_url = build_password_reset_url(
            case["workspace"], case["uid"], case["token"]
        )

        print(f"Generated URL: {reset_url}")
        print("-" * 60)


if __name__ == "__main__":
    test_workspace_scenarios()

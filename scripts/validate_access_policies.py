#!/usr/bin/env python3
"""
Validation script for Access Policy implementation.
Run this to verify policies are properly configured.

Usage:
    python scripts/validate_access_policies.py
"""

import os
import sys
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()

from users.models import User, RoleDefaultPrivilege, SpecialPrivilege
from common.status import Roles


def validate_policy_imports():
    """Validate all policy files can be imported"""
    print("✅ Validating policy imports...")
    
    try:
        from users.access_policies import BaseSchoolAccessPolicy, UserAccessPolicy
        from academics.access_policies import AcademicsAccessPolicy
        from finance.access_policies import TransactionAccessPolicy, FinanceAccessPolicy
        from students.access_policies import StudentAccessPolicy
        from grading.access_policies import GradebookAccessPolicy
        from staff.access_policies import StaffAccessPolicy
        from reports.access_policies import ReportsAccessPolicy
        from settings.access_policies import SettingsAccessPolicy
        
        print("  ✓ All policy files import successfully")
        return True
    except ImportError as e:
        print(f"  ✗ Import error: {e}")
        return False


def validate_privilege_codes():
    """Validate privilege codes in database match expected format"""
    print("\n✅ Validating privilege codes...")
    
    role_privileges = RoleDefaultPrivilege.objects.all()
    
    if role_privileges.count() == 0:
        print("  ⚠ No role privileges found - run migration 0003_populate_role_privileges")
        return False
    
    print(f"  ✓ Found {role_privileges.count()} role privilege mappings")
    
    # Check for uppercase codes
    lowercase_codes = role_privileges.exclude(privilege_code__regex=r'^[A-Z_]+$')
    if lowercase_codes.exists():
        print(f"  ⚠ Found {lowercase_codes.count()} non-uppercase privilege codes:")
        for priv in lowercase_codes[:5]:
            print(f"    - {priv.privilege_code}")
        return False
    
    print("  ✓ All privilege codes are uppercase")
    return True


def validate_base_policy():
    """Validate BaseSchoolAccessPolicy has correct methods"""
    print("\n✅ Validating BaseSchoolAccessPolicy...")
    
    from users.access_policies import BaseSchoolAccessPolicy
    
    required_methods = ['has_privilege', 'has_any_privilege', 'is_role_in', '_normalize_code']
    
    for method in required_methods:
        if not hasattr(BaseSchoolAccessPolicy, method):
            print(f"  ✗ Missing method: {method}")
            return False
    
    print("  ✓ All required methods present")
    
    # Check _normalize_code implementation
    policy = BaseSchoolAccessPolicy()
    assert policy._normalize_code("grading_enter") == "GRADING_ENTER"
    assert policy._normalize_code("GRADING_ENTER") == "GRADING_ENTER"
    assert policy._normalize_code("  Grading_Enter  ") == "GRADING_ENTER"
    
    print("  ✓ _normalize_code works correctly")
    return True


def validate_user_model():
    """Validate User model has required privilege methods"""
    print("\n✅ Validating User model...")
    
    required_methods = ['has_privilege', 'get_privileges', 'get_student', 'get_staff', 'get_children']
    
    for method in required_methods:
        if not hasattr(User, method):
            print(f"  ✗ Missing method: {method}")
            return False
    
    print("  ✓ All required methods present")
    return True


def test_privilege_resolution():
    """Test privilege resolution with a sample user"""
    print("\n✅ Testing privilege resolution...")
    
    # Check if we have any users
    if not User.objects.exists():
        print("  ⚠ No users found - skipping privilege resolution test")
        return True
    
    # Create test user if needed
    test_user = User.objects.filter(role=Roles.TEACHER).first()
    
    if not test_user:
        print("  ⚠ No teacher user found - skipping privilege resolution test")
        return True
    
    print(f"  Testing with user: {test_user.email} (role: {test_user.role})")
    
    # Test has_privilege
    privileges = test_user.get_privileges()
    print(f"  ✓ User has {len(privileges)} privileges")
    
    if "GRADING_ENTER" in privileges:
        assert test_user.has_privilege("GRADING_ENTER") == True
        assert test_user.has_privilege("grading_enter") == True  # Case insensitive
        print("  ✓ has_privilege works (case-insensitive)")
    
    return True


def main():
    """Run all validation checks"""
    print("=" * 60)
    print("Access Policy Implementation Validation")
    print("=" * 60)
    
    results = [
        validate_policy_imports(),
        validate_base_policy(),
        validate_user_model(),
        validate_privilege_codes(),
        test_privilege_resolution(),
    ]
    
    print("\n" + "=" * 60)
    if all(results):
        print("✅ All validation checks passed!")
        print("\nNext steps:")
        print("1. Run migrations: python manage.py migrate users")
        print("2. Wire policies to views (see ACCESS_POLICY_IMPLEMENTATION.md)")
        print("3. Test with actual requests")
    else:
        print("❌ Some validation checks failed - review errors above")
        sys.exit(1)
    print("=" * 60)


if __name__ == '__main__':
    main()

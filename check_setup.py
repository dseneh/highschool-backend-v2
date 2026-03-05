#!/usr/bin/env python
"""Railway setup checks - avoids printing code in logs"""
import sys
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()

from django.contrib.auth import get_user_model
from core.models import Tenant
from users.models import Permission
from django_tenants.utils import get_public_schema_name

def check_superuser_exists():
    """Check if superadmin user exists"""
    User = get_user_model()
    exists = User.objects.filter(role='superadmin').exists()
    print('true' if exists else 'false')

def check_public_tenant_exists():
    """Check if public tenant exists"""
    try:
        Tenant.objects.get(schema_name=get_public_schema_name())
        print('true')
    except Tenant.DoesNotExist:
        print('false')

def check_permissions_exist():
    """Check if permissions are loaded"""
    exists = Permission.objects.exists()
    print('true' if exists else 'false')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: check_setup.py {superuser|public_tenant|permissions}')
        sys.exit(1)
    
    check_type = sys.argv[1]
    
    if check_type == 'superuser':
        check_superuser_exists()
    elif check_type == 'public_tenant':
        check_public_tenant_exists()
    elif check_type == 'permissions':
        check_permissions_exist()
    else:
        print(f'Unknown check: {check_type}', file=sys.stderr)
        sys.exit(1)

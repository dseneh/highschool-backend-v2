#!/usr/bin/env python
"""
Fix or create superadmin user with proper fields
Run this with: railway run python fix_superuser.py
Or locally: python fix_superuser.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()

from django.contrib.auth import get_user_model
from common.status import Roles, UserAccountType

User = get_user_model()

def fix_or_create_superuser():
    email = "admin@ezyschool.app"
    password = "Ezyschool.net"
    username = "admin"
    
    try:
        # Try to get existing user
        user = User.objects.get(email=email)
        print(f"Found existing user: {email}")
        
        # Force-update all fields
        user.username = username
        user.role = Roles.SUPERADMIN
        user.account_type = UserAccountType.GLOBAL
        user.first_name = "System"
        user.last_name = "Administrator"
        user.id_number = "admin001"
        user.is_active = True
        user.set_password(password)
        user.save()
        print("  ✓ Updated all fields (forced)")
            
    except User.DoesNotExist:
        # Create new user using the same approach as setup.py
        print(f"User {email} does not exist. Creating new superuser...")
        user = User.objects.create_superuser(
            email=email,
            username=username,
            password=password,
            first_name="System",
            last_name="Administrator",
            id_number="admin001",
            account_type=UserAccountType.GLOBAL,
            role=Roles.SUPERADMIN,
        )
        print("  ✓ Created superuser with all fields")
    
    print(f"\n✅ Superuser is ready!")
    
    print("\n" + "="*60)
    print("Superuser Credentials:")
    print("="*60)
    print(f"Email:       {user.email}")
    print(f"Username:    {user.username}")
    print(f"Password:    {password}")
    print(f"ID Number:   {user.id_number}")
    print(f"Role:        {user.role}")
    print(f"Name:        {user.first_name} {user.last_name}")
    print("="*60)

if __name__ == '__main__':
    fix_or_create_superuser()

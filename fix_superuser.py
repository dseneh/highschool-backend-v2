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
    
    try:
        # Try to get existing user
        user = User.objects.get(email=email)
        print(f"Found existing user: {email}")
        
        # Update fields if missing
        updated = False
        if not user.username:
            user.username = "admin"
            updated = True
            print("  ✓ Set username to 'admin'")
        
        if user.role != Roles.SUPERADMIN:
            user.role = Roles.SUPERADMIN
            updated = True
            print("  ✓ Set role to 'superadmin'")
        
        if user.account_type != UserAccountType.GLOBAL:
            user.account_type = UserAccountType.GLOBAL
            updated = True
            print("  ✓ Set account_type to 'GLOBAL'")
        
        if not user.first_name:
            user.first_name = "System"
            user.last_name = "Administrator"
            updated = True
            print("  ✓ Set name to 'System Administrator'")
        
        if not user.id_number:
            user.id_number = "admin001"
            updated = True
            print("  ✓ Set id_number to 'admin001'")
        
        # Reset password
        user.set_password(password)
        updated = True
        print("  ✓ Reset password")
        
        if updated:
            user.save()
            print(f"\n✅ Successfully updated user: {email}")
        else:
            print(f"\n✅ User already has all required fields")
            
    except User.DoesNotExist:
        # Create new user
        print(f"User {email} does not exist. Creating new superuser...")
        user = User.objects.create_superuser(
            email=email,
            username="admin",
            password=password,
            first_name="System",
            last_name="Administrator",
            id_number="admin001",
            role=Roles.SUPERADMIN,
            account_type=UserAccountType.GLOBAL,
            is_active=True,
        )
        print(f"✅ Successfully created superuser: {email}")
    
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

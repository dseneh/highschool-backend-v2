"""
Management command to create a global superadmin user.

IMPORTANT: Before creating a superadmin, you must create the public tenant first:
    python manage.py create_public_tenant --domain_url public.localhost --owner_email admin@example.com

Then you can create additional superusers using this command.

Usage:
    python manage.py create_superadmin --email admin@example.com --password changeme123
"""

import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django_tenants.utils import get_public_schema_name
from django.db import connection

User = get_user_model()


class Command(BaseCommand):
    help = "Create a global superadmin user (for multi-tenant system)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            default=None,
            help="Superadmin email (required)",
        )
        parser.add_argument(
            "--password",
            type=str,
            default=None,
            help="Superadmin password (required)",
        )
        parser.add_argument(
            "--id-number",
            type=str,
            default=None,
            help="Superadmin ID number (optional, auto-generated if not provided)",
        )
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="Superadmin name (optional)",
        )

    def handle(self, *args, **options):
        # Ensure we're in the public schema
        if connection.schema_name != get_public_schema_name():
            connection.set_schema_to_public()
        
        # Get credentials from arguments or environment variables
        email = options.get("email") or os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = options.get("password") or os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        id_number = options.get("id_number") or os.environ.get("DJANGO_SUPERUSER_ID_NUMBER", "admin001")
        name = options.get("name") or os.environ.get("DJANGO_SUPERUSER_NAME", "System Administrator")

        if not email:
            self.stdout.write(
                self.style.ERROR(
                    "Email is required. Provide --email or set DJANGO_SUPERUSER_EMAIL environment variable."
                )
            )
            return

        if not password:
            self.stdout.write(
                self.style.ERROR(
                    "Password is required. Provide --password or set DJANGO_SUPERUSER_PASSWORD environment variable."
                )
            )
            return

        # Check if public tenant exists (required for django-tenant-users)
        try:
            from core.models import Tenant
            public_schema = get_public_schema_name()
            Tenant.objects.get(schema_name=public_schema)
        except Tenant.DoesNotExist:
            raise CommandError(
                "Public tenant does not exist. Please create it first:\n"
                "  python manage.py create_public_tenant --domain_url public.localhost --owner_email <email>\n"
                "This will create the public tenant and the first owner user."
            )

        # Check if user with this email already exists
        # Note: In django-tenant-users, is_superuser is stored in UserTenantPermissions, not on User model
        if User.objects.filter(email=email).exists():
            self.stdout.write(
                self.style.WARNING(f"User with email '{email}' already exists.")
            )
            return

        try:
            # Create superuser using UserProfile's create_superuser method
            # UserProfile.create_superuser expects: password, email, **extra_fields
            user = User.objects.create_superuser(
                password=password,
                email=email,
                id_number=id_number,
                name=name,
                is_active=True,
            )

            # Note: is_superuser and is_staff are properties in django-tenant-users
            # that check UserTenantPermissions, not direct fields
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Successfully created global superadmin:\n"
                    f"  Email: {user.email}\n"
                    f"  ID Number: {user.id_number}\n"
                    f"  Name: {getattr(user, 'name', 'N/A')}\n"
                    f"  User created with superuser privileges in public tenant"
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error creating superadmin: {e}")
            )
            import traceback
            traceback.print_exc()

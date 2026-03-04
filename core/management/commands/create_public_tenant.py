"""
Custom management command to create public tenant with superuser owner.

This wraps django-tenant-users' create_public_tenant and automatically:
1. Creates the public tenant
2. Sets a password for the owner (if provided)
3. Makes the owner a superuser in the public tenant

Usage:
    python manage.py create_public_tenant --domain_url public.localhost --owner_email admin@example.com --password changeme123
"""

import os
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context, get_public_schema_name
from tenant_users.tenants.utils import create_public_tenant
from tenant_users.tenants.models import ExistsError, SchemaError
from tenant_users.permissions.models import UserTenantPermissions

from common.status import Roles


class Command(BaseCommand):
    help = "Creates the initial public tenant with superuser owner"

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain_url",
            required=True,
            type=str,
            help="The URL for the public tenant's domain.",
        )
        parser.add_argument(
            "--owner_email",
            required=True,
            type=str,
            help="Email address of the owner user.",
        )
        parser.add_argument(
            "--password",
            type=str,
            default=None,
            help="Password for the owner user. If not provided, will prompt or use environment variable.",
        )
        parser.add_argument(
            "--id-number",
            type=str,
            default=None,
            help="ID number for the owner user (optional).",
        )
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="Name for the owner user (optional).",
        )
        parser.add_argument(
            "--username",
            type=str,
            default=None,
            help="Username for the owner user (optional, defaults to 'admin').",
        )

    def handle(self, domain_url: str, owner_email: str, **options):
        password = options.get("password") or os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        id_number = options.get("id_number") or os.environ.get("DJANGO_SUPERUSER_ID_NUMBER", "admin01")
        # name = options.get("name") or os.environ.get("DJANGO_SUPERUSER_NAME", "Super Admin")
        username = options.get("username", 'admin') or os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin")

        # Prompt for password if not provided
        if not password:
            from getpass import getpass
            password = getpass("Enter password for owner user: ")
            if not password:
                raise CommandError("Password is required")

        try:
            # Prepare owner extra data
            owner_extra = {
                "password": password,
            }
            
            # Add optional fields if provided
            from users.models import User
            user_fields = {f.name for f in User._meta.get_fields() if hasattr(f, 'name')}
            if username and 'username' in user_fields:
                owner_extra["username"] = username
            if id_number and 'id_number' in user_fields:
                owner_extra["id_number"] = id_number
            owner_extra["is_default_password"] = False
            owner_extra["role"] = Roles.SUPERADMIN

            # Create public tenant with superuser privileges
            public_tenant, domain, profile = create_public_tenant(
                domain_url=domain_url,
                owner_email=owner_email,
                is_superuser=True,  # Make owner a superuser
                is_staff=True,      # Make owner staff
                **owner_extra
            )

            # Build success message
            success_msg = (
                f"✓ Successfully created public tenant:\n"
                f"  Domain: {domain.domain}\n"
                f"  Owner Email: {profile.email}\n"
            )
            if hasattr(profile, 'username') and profile.username:
                success_msg += f"  Owner Username: {profile.username}\n"
            if hasattr(profile, 'id_number') and profile.id_number:
                success_msg += f"  Owner ID Number: {profile.id_number}\n"
            if hasattr(profile, 'name') and profile.name:
                success_msg += f"  Owner Name: {profile.name}\n"
            success_msg += (
                f"  Owner is superuser: Yes\n"
                f"  Owner is staff: Yes\n"
                f"  Password: Set"
            )
            self.stdout.write(self.style.SUCCESS(success_msg))

        except ExistsError as e:
            self.stdout.write(
                self.style.ERROR(f"✗ Public tenant already exists: {e}")
            )
        except SchemaError as e:
            self.stdout.write(
                self.style.ERROR(f"✗ Schema error: {e}")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"✗ Error creating public tenant: {e}")
            )
            import traceback
            traceback.print_exc()
            raise CommandError(f"Failed to create public tenant: {e}")


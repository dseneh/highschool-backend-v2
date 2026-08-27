"""
Management command to create a platform Super Admin.

IMPORTANT: Before creating a Super Admin, you must create the public tenant first:
    python manage.py create_public_tenant --domain_url public.localhost --owner_email admin@example.com

Then you can create additional platform Super Admins using this command.

Usage:
    python manage.py create_superadmin --email admin@example.com --password changeme123
"""

import os
import secrets
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django_tenants.utils import get_public_schema_name
from django.db import connection

User = get_user_model()


def generate_platform_id() -> str:
    """Return a unique five-character platform-user identifier."""
    while True:
        candidate = f"G{secrets.token_hex(2).upper()}"
        if not User.objects.filter(id_number=candidate).exists():
            return candidate


def generate_username(email: str) -> str:
    """Return an available username based on the email local part."""
    base = email.split("@", 1)[0] or "admin"
    candidate = base
    index = 1
    while User.objects.filter(username=candidate).exists():
        candidate = f"{base}_{index}"
        index += 1
    return candidate


class Command(BaseCommand):
    help = "Create a platform Super Admin user for the multi-tenant system"

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            default=None,
            help="Super Admin email (required)",
        )
        parser.add_argument(
            "--password",
            type=str,
            default=None,
            help="Super Admin password (required)",
        )
        parser.add_argument(
            "--id-number",
            type=str,
            default=None,
            help="Super Admin ID number (optional, auto-generated if not provided)",
        )
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="Super Admin name (optional)",
        )

    def handle(self, *args, **options):
        # Ensure we're in the public schema
        if connection.schema_name != get_public_schema_name():
            connection.set_schema_to_public()

        # Get credentials from arguments or environment variables
        email = options.get("email") or os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = options.get("password") or os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        requested_id_number = options.get("id_number") or os.environ.get("DJANGO_SUPERUSER_ID_NUMBER")
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

        try:
            # Split name into first_name and last_name
            name_parts = name.split(" ", 1) if name else ["Admin", ""]
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ""

            existing_user = User.objects.filter(email__iexact=email).first()
            if existing_user:
                user = existing_user
                user.is_active = True
                user.is_platform_superuser = True
                user.set_password(password)
                user.save(update_fields=["is_active", "is_platform_superuser", "password"])
                from core.models import Tenant
                from tenant_users.permissions.models import UserTenantPermissions
                from users.access_service import sync_account_scope

                public_tenant = Tenant.objects.get(schema_name=get_public_schema_name())
                if not public_tenant.user_set.filter(pk=user.pk).exists():
                    public_tenant.add_user(user, is_superuser=True, is_staff=True)
                else:
                    permissions = UserTenantPermissions.objects.get(profile=user)
                    permissions.is_superuser = True
                    permissions.is_staff = True
                    permissions.save(update_fields=["is_superuser", "is_staff"])
                sync_account_scope(user)
                self.stdout.write(
                    self.style.WARNING(
                        f"User with email '{email}' already exists; upgraded it to a platform Super Admin."
                    )
                )
                return

            username = generate_username(email)
            id_number = requested_id_number or generate_platform_id()
            if User.objects.filter(id_number=id_number).exists():
                id_number = generate_platform_id()

            from common.status import UserAccountScope, UserAccountType

            # Platform authority is access metadata, not a user persona. A new
            # platform-only identity therefore starts with the neutral OTHER
            # persona and explicit PLATFORM scope.
            user = User.objects.create_superuser(
                email=email,
                username=username,
                password=password,
                first_name=first_name,
                last_name=last_name,
                id_number=id_number,
                account_type=UserAccountType.OTHER,
                account_scope=UserAccountScope.PLATFORM.value,
                is_platform_superuser=True,
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Successfully created platform Super Admin:\n"
                    f"  Email: {user.email}\n"
                    f"  Username: {user.username}\n"
                    f"  ID Number: {user.id_number}\n"
                    f"  Name: {user.first_name} {user.last_name}\n"
                    f"  User created with platform Super Admin privileges"
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating Super Admin: {e}"))
            import traceback

            traceback.print_exc()

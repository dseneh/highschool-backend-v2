"""
Custom management command to grant superadmin users access to all tenants.

This command:
1. Finds all users with role=SUPERADMIN
2. Adds them to all existing tenants with is_superuser=True, is_staff=True

Usage:
    python manage.py grant_superadmin_access
    python manage.py grant_superadmin_access --superadmin-email admin@example.com
    python manage.py grant_superadmin_access --tenant-schema myschool (grant to single tenant)
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django_tenants.utils import schema_context, get_public_schema_name

from core.models import Tenant
from users.models import User
from common.status import Roles


class Command(BaseCommand):
    help = "Grant superadmin users access to all tenants"

    def add_arguments(self, parser):
        parser.add_argument(
            "--superadmin-email",
            type=str,
            default=None,
            help="Email of superadmin user to grant access (optional, defaults to all superadmins)",
        )
        parser.add_argument(
            "--tenant-schema",
            type=str,
            default=None,
            help="Schema name of specific tenant to grant access (optional, defaults to all tenants)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )

    def handle(self, superadmin_email=None, tenant_schema=None, dry_run=False, **options):
        verbosity = options.get("verbosity", 1)

        # Ensure we're in the public schema
        if connection.schema_name != get_public_schema_name():
            raise CommandError("This command must be run in the public schema")

        # Get superadmin users
        if superadmin_email:
            try:
                superadmins = [User.objects.get(email=superadmin_email)]
                if superadmins[0].role != Roles.SUPERADMIN:
                    raise CommandError(f"User {superadmin_email} is not a superadmin (role={superadmins[0].role})")
            except User.DoesNotExist:
                raise CommandError(f"Superadmin user with email '{superadmin_email}' not found")
        else:
            superadmins = list(User.objects.filter(role=Roles.SUPERADMIN))
            if not superadmins:
                self.stdout.write(self.style.WARNING("No superadmin users found"))
                return

        if verbosity >= 1:
            self.stdout.write(f"Found {len(superadmins)} superadmin(s)")
            for admin in superadmins:
                self.stdout.write(f"  - {admin.email} ({admin.id})")

        # Get tenants
        public_schema = get_public_schema_name()
        if tenant_schema:
            try:
                tenants = [Tenant.objects.get(schema_name=tenant_schema)]
            except Tenant.DoesNotExist:
                raise CommandError(f"Tenant with schema_name '{tenant_schema}' not found")
        else:
            tenants = list(
                Tenant.objects
                .exclude(schema_name=public_schema)
                .exclude(status="deleted")
            )
            if not tenants:
                self.stdout.write(self.style.WARNING("No tenants found"))
                return

        if verbosity >= 1:
            self.stdout.write(f"Found {len(tenants)} tenant(s)")
            for tenant in tenants:
                self.stdout.write(f"  - {tenant.name} ({tenant.schema_name})")

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\nDRY RUN: Would grant {len(superadmins)} superadmin(s) access to {len(tenants)} tenant(s)"
            ))
            return

        # Grant access
        total_added = 0
        total_skipped = 0

        for tenant in tenants:
            self.stdout.write(f"\nProcessing tenant: {tenant.name} ({tenant.schema_name})")

            with schema_context(tenant.schema_name):
                for superadmin in superadmins:
                    try:
                        # Check if user is already added to this tenant
                        # Use filter to check existence
                        from tenant_users.tenants.models import TenantUser
                        existing = TenantUser.objects.filter(
                            tenant=tenant,
                            user=superadmin
                        ).exists()

                        if existing:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  ✓ {superadmin.email} already has access"
                                )
                            )
                            total_skipped += 1
                        else:
                            # Add user to tenant
                            tenant.add_user(superadmin, is_superuser=True, is_staff=True)
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"  ✓ Added {superadmin.email} to tenant"
                                )
                            )
                            total_added += 1
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"  ✗ Failed to add {superadmin.email}: {e}"
                            )
                        )

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(f"Added: {total_added}"))
        self.stdout.write(self.style.WARNING(f"Skipped (already exists): {total_skipped}"))
        self.stdout.write("=" * 60)

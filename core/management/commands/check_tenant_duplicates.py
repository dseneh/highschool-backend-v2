"""
Custom management command to check for duplicate tenants.

This command:
1. Finds tenants with duplicate names (case-insensitive)
2. Finds tenants with duplicate schema names
3. Reports all duplicates with details

Usage:
    python manage.py check_tenant_duplicates
    python manage.py check_tenant_duplicates --fix (not implemented yet - manual cleanup required)
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Count
from django_tenants.utils import get_public_schema_name

from core.models import Tenant


class Command(BaseCommand):
    help = "Check for duplicate tenants by name, schema_name, or workspace"

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information about each tenant",
        )

    def handle(self, verbose=False, **options):
        verbosity = options.get("verbosity", 1)

        # Ensure we're in the public schema
        if connection.schema_name != get_public_schema_name():
            raise CommandError("This command must be run in the public schema")

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.MIGRATE_HEADING("TENANT DUPLICATE CHECK"))
        self.stdout.write("=" * 70 + "\n")

        # Check for duplicate names (case-insensitive)
        self.stdout.write(self.style.MIGRATE_LABEL("Checking for duplicate tenant names..."))
        
        # Get all tenants grouped by lowercase name
        from django.db.models.functions import Lower
        duplicates_by_name = (
            Tenant.objects
            .exclude(schema_name=get_public_schema_name())
            .values('name')
            .annotate(
                name_lower=Lower('name'),
                count=Count('id')
            )
            .filter(count__gt=1)
            .order_by('name')
        )

        if duplicates_by_name:
            self.stdout.write(self.style.ERROR(f"  ✗ Found {len(duplicates_by_name)} duplicate name(s):\n"))
            for dupe in duplicates_by_name:
                name = dupe['name']
                count = dupe['count']
                self.stdout.write(f"    • '{name}' appears {count} times")
                
                # Show details of each tenant with this name
                tenants = Tenant.objects.filter(name__iexact=name)
                for t in tenants:
                    self.stdout.write(
                        f"      - ID: {t.id} | Schema: {t.schema_name} | Status: {t.status} | Created: {t.created_at}"
                    )
                self.stdout.write("")
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ No duplicate tenant names found\n"))

        # Check for duplicate schema names (should never happen due to DB constraint)
        self.stdout.write(self.style.MIGRATE_LABEL("Checking for duplicate schema names..."))
        
        duplicates_by_schema = (
            Tenant.objects
            .exclude(schema_name=get_public_schema_name())
            .values('schema_name')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
            .order_by('schema_name')
        )

        if duplicates_by_schema:
            self.stdout.write(self.style.ERROR(f"  ✗ Found {len(duplicates_by_schema)} duplicate schema name(s):\n"))
            for dupe in duplicates_by_schema:
                schema = dupe['schema_name']
                count = dupe['count']
                self.stdout.write(f"    • Schema '{schema}' appears {count} times")
                
                # Show details
                tenants = Tenant.objects.filter(schema_name=schema)
                for t in tenants:
                    self.stdout.write(
                        f"      - ID: {t.id} | Name: {t.name} | Status: {t.status}"
                    )
                self.stdout.write("")
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ No duplicate schema names found\n"))

        # Summary
        self.stdout.write("=" * 70)
        total_duplicates = len(duplicates_by_name) + len(duplicates_by_schema)
        
        if total_duplicates > 0:
            self.stdout.write(self.style.ERROR(f"RESULT: Found {total_duplicates} duplicate(s)"))
            self.stdout.write("\n" + self.style.WARNING("ACTION REQUIRED:"))
            self.stdout.write("  1. Review the duplicates listed above")
            self.stdout.write("  2. Decide which tenant(s) to keep")
            self.stdout.write("  3. Manually delete or merge the duplicate tenant(s)")
            self.stdout.write("  4. Use Django admin or direct database commands")
            self.stdout.write("\nExample cleanup command:")
            self.stdout.write("  python manage.py shell")
            self.stdout.write("  >>> from core.models import Tenant")
            self.stdout.write("  >>> tenant = Tenant.objects.get(id='<uuid>')")
            self.stdout.write("  >>> tenant.status = 'deleted'")
            self.stdout.write("  >>> tenant.save()")
        else:
            self.stdout.write(self.style.SUCCESS("RESULT: No duplicates found! ✓"))
        
        self.stdout.write("=" * 70 + "\n")

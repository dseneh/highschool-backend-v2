"""Hard-delete a tenant workspace and its schema.

This command permanently deletes a tenant by:
1) Dropping the tenant PostgreSQL schema with CASCADE.
2) Deleting the tenant row in the public schema.

Usage examples:
  python manage.py hard_delete_tenant_workspace --schema-name acme_school
  python manage.py hard_delete_tenant_workspace --schema-name acme_school --yes
  python manage.py hard_delete_tenant_workspace --schema-name acme_school --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django_tenants.utils import get_public_schema_name

from core.models import Tenant
from core.services.tenant_deletion import hard_delete_tenant_workspace


class Command(BaseCommand):
    help = "Permanently delete a tenant workspace and drop its schema."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema-name",
            required=True,
            help="Tenant schema name to purge (e.g. school_one).",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip interactive confirmation prompt.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making changes.",
        )

    def handle(self, *args, **options):
        schema_name = str(options["schema_name"]).strip()
        assume_yes = bool(options["yes"])
        dry_run = bool(options["dry_run"])

        public_schema = get_public_schema_name()

        if connection.schema_name != public_schema:
            raise CommandError(
                f"This command must run in the public schema. Current schema: {connection.schema_name}"
            )

        if not schema_name:
            raise CommandError("--schema-name is required.")

        if schema_name == public_schema:
            raise CommandError("Refusing to delete the public schema tenant.")

        try:
            tenant = Tenant.objects.get(schema_name=schema_name)
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"Tenant not found for schema_name='{schema_name}'.") from exc

        self.stdout.write(self.style.WARNING("\nPERMANENT DELETE REQUEST"))
        self.stdout.write(f"  Tenant: {tenant.name}")
        self.stdout.write(f"  Schema: {tenant.schema_name}")
        self.stdout.write(f"  Status: {tenant.status}")
        self.stdout.write(f"  Active: {tenant.active}")
        self.stdout.write("  Action: drop schema + delete tenant row\n")

        if not assume_yes:
            prompt = f"Type the exact schema name '{schema_name}' to confirm: "
            confirmation = input(prompt).strip()
            if confirmation != schema_name:
                raise CommandError("Confirmation mismatch. Aborted.")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run complete. No data changed."))
            return

        hard_delete_tenant_workspace(tenant)

        self.stdout.write(self.style.SUCCESS("Tenant workspace deleted successfully."))

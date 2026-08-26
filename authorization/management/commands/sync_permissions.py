from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
from django_tenants.utils import get_public_schema_name, schema_context

from authorization.generator import render_permission_constants
from authorization.registry import (
    get_permission_registry,
    get_platform_permission_registry,
)
from authorization.system_roles import get_system_roles
from authorization.services import (
    ensure_tenant_owner_membership,
    ensure_tenant_user_membership,
    sync_system_roles,
)
from core.models import Tenant


class Command(BaseCommand):
    help = "Validate permission catalogs, generate constants, and seed system roles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            action="append",
            dest="schemas",
            help="Only seed the named tenant schema. May be supplied more than once.",
        )
        parser.add_argument(
            "--skip-database",
            action="store_true",
            help="Validate catalogs and generate constants without seeding tenant roles.",
        )

    def handle(self, *args, **options):
        tenant_registry = get_permission_registry()
        platform_registry = get_platform_permission_registry()
        system_roles = get_system_roles()

        self._write_constants(tenant_registry, platform_registry)
        self.stdout.write(
            self.style.SUCCESS(
                f"Validated {len(tenant_registry.permissions)} tenant permissions, "
                f"{len(platform_registry.permissions)} platform permissions, and "
                f"{len(system_roles)} system roles."
            )
        )

        if options["skip_database"]:
            return

        schemas = self._resolve_schemas(options.get("schemas"))
        for schema_name in schemas:
            try:
                with schema_context(get_public_schema_name()):
                    tenant = Tenant.objects.select_related("owner").get(
                        schema_name=schema_name
                    )
                    owner = tenant.owner
                with schema_context(schema_name), transaction.atomic():
                    sync_system_roles()
                    ensure_tenant_owner_membership(owner)
                    from tenant_users.permissions.models import UserTenantPermissions

                    for tenant_user in UserTenantPermissions.objects.select_related(
                        "profile"
                    ):
                        ensure_tenant_user_membership(tenant_user.profile)
            except ValidationError as exc:
                raise CommandError(f"Failed to sync {schema_name}: {exc}") from exc
            self.stdout.write(
                self.style.SUCCESS(f"Synchronized system roles in {schema_name}.")
            )

    def _resolve_schemas(self, requested_schemas):
        if isinstance(requested_schemas, str):
            requested_schemas = [requested_schemas]
        public_schema = get_public_schema_name()
        with schema_context(public_schema):
            queryset = Tenant.objects.exclude(schema_name=public_schema)
            if requested_schemas:
                queryset = queryset.filter(schema_name__in=requested_schemas)
            schemas = list(queryset.values_list("schema_name", flat=True))

        missing = set(requested_schemas or ()) - set(schemas)
        if missing:
            raise CommandError(
                f"Unknown tenant schemas: {', '.join(sorted(missing))}"
            )
        return schemas

    def _write_constants(self, tenant_registry, platform_registry):
        authorization_dir = Path(__file__).resolve().parents[2]
        outputs = (
            (
                authorization_dir / "generated_permissions.py",
                render_permission_constants(
                    tenant_registry,
                    root_class="Permissions",
                ),
            ),
            (
                authorization_dir / "generated_platform_permissions.py",
                render_permission_constants(
                    platform_registry,
                    root_class="PlatformPermissions",
                ),
            ),
        )
        for path, source in outputs:
            if not path.exists() or path.read_text(encoding="utf-8") != source:
                path.write_text(source, encoding="utf-8")

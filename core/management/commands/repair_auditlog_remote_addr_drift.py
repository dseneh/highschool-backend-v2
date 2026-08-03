"""
Repair auditlog migration drift for remote_addr.

Problem:
- Some schemas already contain auditlog_logentry.remote_addr
- django_migrations in those schemas does not contain auditlog.0003_logentry_remote_addr
- migrate_schemas then fails with DuplicateColumn

This command checks each schema and records the migration as applied only when:
1) auditlog_logentry exists with remote_addr column, and
2) auditlog.0003_logentry_remote_addr is missing from django_migrations.
"""

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context


MIGRATION_APP = "auditlog"
MIGRATION_NAME = "0003_logentry_remote_addr"


class Command(BaseCommand):
    help = "Repair auditlog remote_addr migration drift across tenant schemas"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply fixes. Without this flag, runs in dry-run mode.",
        )
        parser.add_argument(
            "--schema",
            action="append",
            dest="schemas",
            help="Optional schema(s) to limit the repair scope. Can be passed multiple times.",
        )
        parser.add_argument(
            "--full-auditlog-chain",
            action="store_true",
            help=(
                "Also mark all missing auditlog migrations as applied when the "
                "auditlog_logentry table already includes modern columns."
            ),
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        specified_schemas = options.get("schemas") or []
        full_chain = options.get("full_auditlog_chain", False)

        schemas = self._resolve_schemas(specified_schemas)
        self.stdout.write(f"Inspecting {len(schemas)} schema(s) for auditlog migration drift...")

        all_auditlog_migrations = self._all_auditlog_migration_names()

        fixed = 0
        pending = 0

        for schema_name in schemas:
            with schema_context(schema_name):
                column_exists = self._remote_addr_column_exists(schema_name)
                migration_applied = self._migration_applied()

                if column_exists and not migration_applied:
                    pending += 1
                    if apply_changes:
                        recorder = MigrationRecorder(connection)
                        recorder.record_applied(MIGRATION_APP, MIGRATION_NAME)
                        fixed += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"[fixed] {schema_name}: recorded {MIGRATION_APP}.{MIGRATION_NAME}"
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"[dry-run] {schema_name}: would record {MIGRATION_APP}.{MIGRATION_NAME}"
                            )
                        )
                else:
                    self.stdout.write(
                        f"[ok] {schema_name}: column_exists={column_exists}, migration_applied={migration_applied}"
                    )

                if full_chain:
                    chain_result = self._repair_full_chain(
                        schema_name=schema_name,
                        all_migrations=all_auditlog_migrations,
                        apply_changes=apply_changes,
                    )
                    fixed += chain_result["fixed"]
                    pending += chain_result["pending"]

        if apply_changes:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Repair complete. Applied fixes: {fixed}. Schemas inspected: {len(schemas)}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run complete. Pending fixes: {pending}. Run with --apply to fix."
                )
            )

    def _resolve_schemas(self, specified_schemas):
        if specified_schemas:
            return specified_schemas

        public_schema = get_public_schema_name()
        Tenant = get_tenant_model()
        tenant_schemas = list(
            Tenant.objects.exclude(schema_name=public_schema).values_list("schema_name", flat=True)
        )
        return [public_schema, *tenant_schemas]

    def _migration_applied(self):
        return MigrationRecorder(connection).migration_qs.filter(
            app=MIGRATION_APP,
            name=MIGRATION_NAME,
        ).exists()

    def _all_auditlog_migration_names(self):
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        names = [name for (app, name) in loader.disk_migrations.keys() if app == MIGRATION_APP]
        return sorted(names)

    def _repair_full_chain(self, schema_name, all_migrations, apply_changes):
        required_columns = {
            "remote_addr",
            "remote_port",
            "additional_data",
            "serialized_data",
            "cid",
            "actor_email",
        }

        columns = set(self._auditlog_columns(schema_name))
        if not required_columns.issubset(columns):
            return {"fixed": 0, "pending": 0}

        recorder = MigrationRecorder(connection)
        applied = {
            row.name
            for row in recorder.migration_qs.filter(app=MIGRATION_APP).only("name")
        }
        missing = [name for name in all_migrations if name not in applied]
        if not missing:
            return {"fixed": 0, "pending": 0}

        fixed = 0
        if apply_changes:
            for name in missing:
                recorder.record_applied(MIGRATION_APP, name)
                fixed += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[fixed] {schema_name}: recorded {MIGRATION_APP}.{name}"
                    )
                )
            return {"fixed": fixed, "pending": 0}

        for name in missing:
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] {schema_name}: would record {MIGRATION_APP}.{name}"
                )
            )
        return {"fixed": 0, "pending": len(missing)}

    def _remote_addr_column_exists(self, schema_name):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'auditlog_logentry'
                  AND column_name = 'remote_addr'
                LIMIT 1
                """,
                [schema_name],
            )
            return cursor.fetchone() is not None

    def _auditlog_columns(self, schema_name):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'auditlog_logentry'
                """,
                [schema_name],
            )
            return [row[0] for row in cursor.fetchall()]

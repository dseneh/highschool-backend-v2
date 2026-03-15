from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.utils import ProgrammingError
from django_tenants.utils import (
    get_public_schema_name,
    get_tenant_model,
    schema_context,
)

from academics.models import SchoolCalendarEvent, SchoolCalendarEventOccurrence


class Command(BaseCommand):
    help = "Rebuild school calendar event occurrence rows for all events."

    def add_arguments(self, parser):
        parser.add_argument(
            "--event-id",
            dest="event_id",
            type=str,
            help="Optional specific school calendar event id to rebuild.",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Include inactive events when rebuilding occurrences.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview affected event count without modifying occurrence rows.",
        )
        parser.add_argument(
            "--tenant-schema",
            type=str,
            help="Schema name of a specific tenant to process.",
        )
        parser.add_argument(
            "--all-tenants",
            action="store_true",
            help="Process all tenant schemas (excluding public schema).",
        )

    def handle(self, *args, **options):
        include_inactive = bool(options["include_inactive"])
        event_id = options.get("event_id")
        dry_run = bool(options["dry_run"])
        tenant_schema = options.get("tenant_schema")
        all_tenants = bool(options["all_tenants"])

        if tenant_schema and all_tenants:
            raise CommandError("Use either --tenant-schema or --all-tenants, not both.")

        if all_tenants or tenant_schema:
            self._run_for_tenants(
                include_inactive=include_inactive,
                event_id=event_id,
                dry_run=dry_run,
                tenant_schema=tenant_schema,
            )
            return

        try:
            self._run_for_current_schema(
                include_inactive=include_inactive,
                event_id=event_id,
                dry_run=dry_run,
            )
        except ProgrammingError as exc:
            if "school_calendar_event" not in str(exc):
                raise

            self.stdout.write(
                self.style.WARNING(
                    "Current schema does not have school calendar tables; "
                    "falling back to all tenant schemas."
                )
            )
            self._run_for_tenants(
                include_inactive=include_inactive,
                event_id=event_id,
                dry_run=dry_run,
                tenant_schema=None,
            )

    def _run_for_tenants(self, *, include_inactive, event_id, dry_run, tenant_schema):
        tenant_model = get_tenant_model()
        public_schema = get_public_schema_name()

        tenants = tenant_model.objects.all().exclude(schema_name=public_schema)
        if tenant_schema:
            tenants = tenants.filter(schema_name=tenant_schema)

        tenants = list(tenants)
        if not tenants:
            raise CommandError("No matching tenant schemas found.")

        for tenant in tenants:
            self.stdout.write(
                self.style.MIGRATE_LABEL(
                    f"\nProcessing tenant: {tenant.schema_name} ({tenant.name})"
                )
            )
            with schema_context(tenant.schema_name):
                self._run_for_current_schema(
                    include_inactive=include_inactive,
                    event_id=event_id,
                    dry_run=dry_run,
                )

    def _run_for_current_schema(self, *, include_inactive, event_id, dry_run):
        if "school_calendar_event" not in connection.introspection.table_names():
            raise ProgrammingError("relation \"school_calendar_event\" does not exist")

        queryset = SchoolCalendarEvent.objects.all().order_by("start_date", "name")
        if not include_inactive:
            queryset = queryset.filter(active=True)
        if event_id:
            queryset = queryset.filter(id=event_id)

        event_count = queryset.count()
        if event_count == 0:
            self.stdout.write(self.style.WARNING("No matching school calendar events found."))
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: would rebuild occurrences for {event_count} event(s)."
                )
            )
            return

        total_before = 0
        total_after = 0

        for event in queryset:
            before = SchoolCalendarEventOccurrence.objects.filter(event=event).count()
            total_before += before

            event.rebuild_occurrences()

            after = SchoolCalendarEventOccurrence.objects.filter(event=event).count()
            total_after += after

            self.stdout.write(
                f"- {event.name} ({event.id}): {before} -> {after} occurrence row(s)"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Rebuild complete. "
                f"Events: {event_count}, occurrences before: {total_before}, after: {total_after}."
            )
        )

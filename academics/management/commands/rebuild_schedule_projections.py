from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from academics.models import SectionSchedule
from academics.services import sync_schedule_projections_for_class_schedule


class Command(BaseCommand):
    help = "Rebuild teacher, gradebook, and student schedule projections from section schedules."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schedule-id",
            type=str,
            help="Rebuild projections for a specific section schedule ID.",
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
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Include inactive section schedules.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview affected schedule count without mutating data.",
        )

    def handle(self, *args, **options):
        if options["tenant_schema"] and options["all_tenants"]:
            raise CommandError("Use either --tenant-schema or --all-tenants, not both.")

        include_inactive = bool(options["include_inactive"])
        schedule_id = options.get("schedule_id")
        dry_run = bool(options["dry_run"])
        tenant_schema = options.get("tenant_schema")
        all_tenants = bool(options["all_tenants"])

        if all_tenants or tenant_schema:
            self._run_for_tenants(
                include_inactive=include_inactive,
                schedule_id=schedule_id,
                dry_run=dry_run,
                tenant_schema=tenant_schema,
            )
            return

        self._run_for_current_schema(
            include_inactive=include_inactive,
            schedule_id=schedule_id,
            dry_run=dry_run,
        )

    def _run_for_tenants(self, *, include_inactive, schedule_id, dry_run, tenant_schema):
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
                    schedule_id=schedule_id,
                    dry_run=dry_run,
                )

    def _run_for_current_schema(self, *, include_inactive, schedule_id, dry_run):
        queryset = SectionSchedule.objects.select_related("section", "period", "subject", "subject__subject")
        if not include_inactive:
            queryset = queryset.filter(active=True)
        if schedule_id:
            queryset = queryset.filter(id=schedule_id)

        schedules = list(queryset.order_by("section__name", "period__name"))
        if not schedules:
            self.stdout.write(self.style.WARNING("No matching section schedules found."))
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: would rebuild projections for {len(schedules)} section schedule(s)."
                )
            )
            return

        for schedule in schedules:
            sync_schedule_projections_for_class_schedule(schedule)
            schedule_label = schedule.subject.subject.name if schedule.subject_id else "Recess"
            self.stdout.write(
                f"- {schedule.section.name} / {schedule.period.name} / {schedule_label} ({schedule.id})"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Projection rebuild complete for {len(schedules)} section schedule(s)."
            )
        )

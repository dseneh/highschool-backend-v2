from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from accounting.services import migrate_legacy_student_bills
from students.models import Enrollment


class Command(BaseCommand):
    help = "Migrate legacy students.StudentEnrollmentBill rows into accounting student bill tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--academic-year",
            type=str,
            help="Filter by academic year ID.",
        )
        parser.add_argument(
            "--student-id",
            type=str,
            help="Filter by student ID.",
        )
        parser.add_argument(
            "--enrollment-id",
            action="append",
            dest="enrollment_ids",
            help="Filter by one or more enrollment IDs (repeatable).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview counts without writing changes.",
        )
        parser.add_argument(
            "--schema",
            type=str,
            help="Run for a specific tenant schema name.",
        )
        parser.add_argument(
            "--all-schemas",
            action="store_true",
            help="Run for all tenant schemas except public.",
        )

    def handle(self, *args, **options):
        academic_year = options.get("academic_year")
        student_id = options.get("student_id")
        enrollment_ids = options.get("enrollment_ids") or []
        dry_run = bool(options.get("dry_run"))
        schema_name = options.get("schema")
        all_schemas = bool(options.get("all_schemas"))

        if schema_name and all_schemas:
            raise CommandError("Use either --schema or --all-schemas, not both.")

        public_schema = get_public_schema_name()
        Tenant = get_tenant_model()

        target_schemas: list[str]
        if all_schemas:
            target_schemas = list(
                Tenant.objects.exclude(schema_name=public_schema).values_list("schema_name", flat=True)
            )
        elif schema_name:
            if schema_name == public_schema:
                self.stdout.write(self.style.WARNING("Public schema skipped. Nothing to migrate there."))
                return
            target_schemas = [schema_name]
        else:
            current_schema = getattr(connection, "schema_name", public_schema)
            if current_schema == public_schema:
                self.stdout.write(
                    self.style.WARNING(
                        "Currently on public schema. Use --schema <tenant> or --all-schemas to run tenant migrations."
                    )
                )
                return
            target_schemas = [current_schema]

        for target_schema in target_schemas:
            self.stdout.write(f"Starting legacy student bill migration for schema: {target_schema}")

            try:
                with schema_context(target_schema):
                    scoped_enrollment_ids = list(enrollment_ids)
                    if academic_year or student_id:
                        qs = Enrollment.objects.all()
                        if academic_year:
                            qs = qs.filter(academic_year_id=academic_year)
                        if student_id:
                            qs = qs.filter(student_id=student_id)
                        matched_ids = [str(pk) for pk in qs.values_list("id", flat=True)]
                        if scoped_enrollment_ids:
                            matched_set = set(matched_ids)
                            scoped_enrollment_ids = [eid for eid in scoped_enrollment_ids if eid in matched_set]
                        else:
                            scoped_enrollment_ids = matched_ids

                        if not scoped_enrollment_ids:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"No enrollments matched the provided filters in schema '{target_schema}'."
                                )
                            )
                            continue

                    with transaction.atomic():
                        summary = migrate_legacy_student_bills(
                            enrollment_ids=scoped_enrollment_ids or None,
                            dry_run=dry_run,
                        )
                        if dry_run:
                            transaction.set_rollback(True)
            except Exception as exc:
                raise CommandError(f"Migration failed for schema '{target_schema}': {exc}") from exc

            if summary.get("skipped_missing_legacy_table"):
                self.stdout.write(
                    self.style.WARNING(
                        f"Schema '{target_schema}': legacy table 'enrollment_bill' does not exist. Skipping."
                    )
                )
                continue

            mode = "DRY RUN" if dry_run else "COMPLETED"
            self.stdout.write(self.style.SUCCESS(f"Schema '{target_schema}' migration {mode}."))
            self.stdout.write(f"  Legacy rows processed: {summary['legacy_rows']}")
            self.stdout.write(f"  Enrollments processed: {summary['enrollments']}")
            self.stdout.write(f"  Accounting bills created: {summary['created_bills']}")
            self.stdout.write(f"  Accounting bills updated: {summary['updated_bills']}")
            self.stdout.write(f"  Accounting lines created: {summary['created_lines']}")

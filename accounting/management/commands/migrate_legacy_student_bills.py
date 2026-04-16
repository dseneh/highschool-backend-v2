from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

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

    def handle(self, *args, **options):
        academic_year = options.get("academic_year")
        student_id = options.get("student_id")
        enrollment_ids = options.get("enrollment_ids") or []
        dry_run = bool(options.get("dry_run"))

        if academic_year or student_id:
            qs = Enrollment.objects.all()
            if academic_year:
                qs = qs.filter(academic_year_id=academic_year)
            if student_id:
                qs = qs.filter(student_id=student_id)
            scoped_ids = [str(pk) for pk in qs.values_list("id", flat=True)]
            if enrollment_ids:
                scoped_set = set(scoped_ids)
                enrollment_ids = [eid for eid in enrollment_ids if eid in scoped_set]
            else:
                enrollment_ids = scoped_ids

        if (academic_year or student_id) and not enrollment_ids:
            self.stdout.write(self.style.WARNING("No enrollments matched the provided filters."))
            return

        self.stdout.write("Starting legacy student bill migration...")

        try:
            with transaction.atomic():
                summary = migrate_legacy_student_bills(
                    enrollment_ids=enrollment_ids or None,
                    dry_run=dry_run,
                )
                if dry_run:
                    transaction.set_rollback(True)
        except Exception as exc:
            raise CommandError(f"Migration failed: {exc}") from exc

        if summary.get("skipped_missing_legacy_table"):
            self.stdout.write(
                self.style.WARNING(
                    "Legacy billing table 'enrollment_bill' does not exist in this tenant schema. Nothing to migrate."
                )
            )
            return

        mode = "DRY RUN" if dry_run else "COMPLETED"
        self.stdout.write(self.style.SUCCESS(f"Legacy student bill migration {mode}."))
        self.stdout.write(f"Legacy rows processed: {summary['legacy_rows']}")
        self.stdout.write(f"Enrollments processed: {summary['enrollments']}")
        self.stdout.write(f"Accounting bills created: {summary['created_bills']}")
        self.stdout.write(f"Accounting bills updated: {summary['updated_bills']}")
        self.stdout.write(f"Accounting lines created: {summary['created_lines']}")

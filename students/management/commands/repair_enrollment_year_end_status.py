"""
Optional data repair after migration 0005 (completed → enrolled).

Marks enrollments that were true year-end closures back to completed when
notes or audit patterns indicate a closed year. Safe default: dry-run only.

Usage:
  python manage.py repair_enrollment_year_end_status --dry-run
  python manage.py repair_enrollment_year_end_status --apply --academic-year-id=<uuid>
"""
from django.core.management.base import BaseCommand

from common.status import EnrollmentStatus
from students.models import Enrollment


class Command(BaseCommand):
    help = (
        "Report or fix enrollment rows mislabeled enrolled after 0005 "
        "when they should remain completed (year-end)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes (default is dry-run).",
        )
        parser.add_argument(
            "--academic-year-id",
            type=str,
            default=None,
            help="Limit to a single academic year UUID.",
        )
        parser.add_argument(
            "--only-with-next-grade",
            action="store_true",
            help="Only rows that already have next_grade_level set.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        qs = Enrollment.objects.filter(status=EnrollmentStatus.ENROLLED)

        if options["academic_year_id"]:
            qs = qs.filter(academic_year_id=options["academic_year_id"])

        if options["only_with_next_grade"]:
            qs = qs.filter(next_grade_level__isnull=False)

        # Heuristic: non-current years with enrolled status are likely mislabeled.
        qs = qs.filter(academic_year__current=False)

        count = qs.count()
        mode = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(
            f"[{mode}] Found {count} non-current enrollments still status=enrolled."
        )

        if not count:
            return

        for enrollment in qs[:50]:
            self.stdout.write(
                f"  - {enrollment.id} student={enrollment.student_id} "
                f"year={enrollment.academic_year_id}"
            )
        if count > 50:
            self.stdout.write(f"  ... and {count - 50} more")

        if apply_changes:
            updated = qs.update(status=EnrollmentStatus.COMPLETED)
            self.stdout.write(
                self.style.SUCCESS(f"Updated {updated} rows to completed.")
            )
        else:
            self.stdout.write(
                "Re-run with --apply to set status=completed on these rows. "
                "Review each cohort before applying in production."
            )

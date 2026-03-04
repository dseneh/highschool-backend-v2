"""
Management command to recalculate student payment summaries.

Usage:
    python manage.py recalculate_payment_summaries --academic-year <id>
    python manage.py recalculate_payment_summaries --enrollment-id <id>
    python manage.py recalculate_payment_summaries --all
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from students.models import Enrollment, StudentPaymentSummary
from finance.utils import calculate_student_payment_summary


class Command(BaseCommand):
    help = "Recalculate student payment summaries for enrollments"

    def add_arguments(self, parser):
        parser.add_argument(
            "--academic-year",
            type=str,
            help="Academic year ID to recalculate summaries for",
        )
        parser.add_argument(
            "--enrollment-id",
            type=str,
            help="Specific enrollment ID to recalculate",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Recalculate all payment summaries",
        )

    def handle(self, *args, **options):
        academic_year_id = options.get("academic_year")
        enrollment_id = options.get("enrollment_id")
        all_summaries = options.get("all")

        if not any([academic_year_id, enrollment_id, all_summaries]):
            raise CommandError(
                "You must specify --academic-year, --enrollment-id, or --all"
            )

        if all_summaries:
            self.stdout.write("Recalculating all payment summaries...")
            enrollments = Enrollment.objects.filter(status="active").select_related(
                "student", "academic_year"
            )
            total_count = enrollments.count()
            self.stdout.write(f"Found {total_count} active enrollments")

        elif enrollment_id:
            try:
                enrollment = Enrollment.objects.get(id=enrollment_id)
                enrollments = [enrollment]
                total_count = 1
                self.stdout.write(
                    f"Recalculating payment summary for enrollment {enrollment_id}"
                )
            except Enrollment.DoesNotExist:
                raise CommandError(f"Enrollment {enrollment_id} not found")

        elif academic_year_id:
            from academics.models import AcademicYear

            try:
                academic_year = AcademicYear.objects.get(id=academic_year_id)
            except AcademicYear.DoesNotExist:
                raise CommandError(f"Academic year {academic_year_id} not found")

            self.stdout.write(
                f"Recalculating payment summaries for academic year: {academic_year.name}"
            )
            enrollments = Enrollment.objects.filter(
                academic_year=academic_year, status="active"
            ).select_related("student", "academic_year")
            total_count = enrollments.count()
            self.stdout.write(f"Found {total_count} active enrollments")

        # Process enrollments
        processed = 0
        errors = 0

        for enrollment in enrollments:
            try:
                calculate_student_payment_summary(
                    enrollment, enrollment.academic_year
                )
                processed += 1

                if processed % 100 == 0:
                    self.stdout.write(
                        f"Progress: {processed}/{total_count} processed, {errors} errors"
                    )

            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"Error processing enrollment {enrollment.id}: {e}"
                    )
                )

        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\nCompleted: {processed} processed, {errors} errors"
            )
        )


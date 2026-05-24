"""Recompute ``AccountingStudentBill.paid_amount`` from the cash ledger.

Useful when the post_save signal wasn't in place yet (legacy bulk uploads),
or after manual data fixes. Safe to run repeatedly.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django_tenants.utils import (
    get_public_schema_name,
    get_tenant_model,
    schema_context,
)

from academics.models import AcademicYear
from accounting.services.payment_allocation import (
    recompute_student_year_payments,
)
from students.models import Student


class Command(BaseCommand):
    help = (
        "Recompute AccountingStudentBill.paid_amount for every student in "
        "every academic year (or a narrowed scope). Source of truth is "
        "AccountingCashTransaction; this rebuilds the denormalized cache."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--academic-year",
            type=str,
            help="Academic year ID to limit the recompute to.",
        )
        parser.add_argument(
            "--student-id",
            type=str,
            help="Student UUID to limit the recompute to.",
        )
        parser.add_argument(
            "--schema",
            type=str,
            help="Tenant schema name to run against.",
        )
        parser.add_argument(
            "--all-schemas",
            action="store_true",
            help="Run for every tenant schema except public.",
        )

    def handle(self, *args, **options):
        academic_year_id = options.get("academic_year")
        student_id = options.get("student_id")
        schema_name = options.get("schema")
        all_schemas = bool(options.get("all_schemas"))

        if schema_name and all_schemas:
            raise CommandError("Use either --schema or --all-schemas, not both.")

        public_schema = get_public_schema_name()
        Tenant = get_tenant_model()

        if all_schemas:
            target_schemas = list(
                Tenant.objects.exclude(schema_name=public_schema).values_list(
                    "schema_name", flat=True
                )
            )
        elif schema_name:
            if schema_name == public_schema:
                self.stdout.write(
                    self.style.WARNING("Public schema skipped.")
                )
                return
            target_schemas = [schema_name]
        else:
            current = getattr(connection, "schema_name", public_schema)
            if current == public_schema:
                self.stdout.write(
                    self.style.WARNING(
                        "On public schema. Pass --schema or --all-schemas."
                    )
                )
                return
            target_schemas = [current]

        for schema in target_schemas:
            self.stdout.write(f"Recomputing bills for schema: {schema}")
            with schema_context(schema):
                self._run_for_current_schema(academic_year_id, student_id)

    def _run_for_current_schema(self, academic_year_id, student_id):
        years = AcademicYear.objects.all()
        if academic_year_id:
            years = years.filter(id=academic_year_id)

        students = Student.objects.all()
        if student_id:
            students = students.filter(id=student_id)

        total_pairs = 0
        for year in years:
            for student in students:
                recompute_student_year_payments(student, year)
                total_pairs += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"  Recomputed {total_pairs} (student, year) pairs."
            )
        )

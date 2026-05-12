"""
Management command to strip leading zeros from existing id_number values for
students, HR employees, and users.

Old format: <2-digit zero-padded school_code><4-digit seq>  e.g. 020001
New format: <school_code><4-digit seq>                       e.g. 20001

Cascade order per tenant schema:
  1. Build old→new id_number mapping for students and HR employees.
  2. Update User.id_number in the public schema for each linked user.
  3. Update student/employee records + their cross-references
     (user_account_id_number).

Usage:
    python manage.py strip_id_leading_zeros [--dry-run] [--schema SCHEMA]
"""

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, schema_context

from core.models import Tenant


def _strip(id_number: str) -> str:
    """Remove leading zeros: '020001' -> '20001'. Non-numeric strings unchanged."""
    if id_number and id_number.isdigit():
        stripped = str(int(id_number))
        return stripped if stripped else id_number
    return id_number


class Command(BaseCommand):
    help = "Strip leading zeros from student, HR employee, and user id_numbers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to the database",
        )
        parser.add_argument(
            "--schema",
            type=str,
            default=None,
            help="Only process a specific tenant schema (default: all tenants)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        target_schema = options.get("schema")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved\n"))

        # Collect tenant schemas to process
        with schema_context(get_public_schema_name()):
            tenants = list(
                Tenant.objects.exclude(schema_name=get_public_schema_name())
                .values_list("schema_name", flat=True)
            )

        if target_schema:
            tenants = [s for s in tenants if s == target_schema]
            if not tenants:
                self.stderr.write(self.style.ERROR(f"Schema '{target_schema}' not found."))
                return

        total_students = total_employees = total_users = 0

        for schema in tenants:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\nProcessing schema: {schema}"))

            with schema_context(schema):
                s, e, u = self._process_tenant(schema, dry_run)
                total_students += s
                total_employees += e
                total_users += u

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Updated: {total_students} students, {total_employees} employees, "
                f"{total_users} users."
            )
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("(DRY RUN — nothing was saved)"))

    def _process_tenant(self, schema: str, dry_run: bool):
        from students.models import Student
        from hr.models import Employee

        student_count = employee_count = user_count = 0

        # ── 1. Students ────────────────────────────────────────────────────────
        # Recompute from school_code + student_seq (authoritative source).
        from common.utils import compute_id_number

        student_renames: dict[str, str] = {}
        students_to_update = []

        for student in Student.objects.only("id", "id_number", "school_code", "student_seq"):
            new_id = compute_id_number(student.school_code, student.student_seq)
            if new_id != student.id_number:
                student_renames[student.id_number] = new_id
                student.id_number = new_id
                students_to_update.append(student)

        if students_to_update:
            self.stdout.write(
                f"  Students: {len(students_to_update)} id_numbers to update"
            )
            if not dry_run:
                with transaction.atomic():
                    Student.objects.bulk_update(students_to_update, ["id_number"])
            student_count = len(students_to_update)

        # ── 2. HR Employees ────────────────────────────────────────────────────
        employee_renames: dict[str, str] = {}
        employees_to_update = []

        for emp in Employee.objects.only("id", "id_number"):
            new_id = _strip(emp.id_number)
            if new_id != emp.id_number:
                employee_renames[emp.id_number] = new_id
                emp.id_number = new_id
                employees_to_update.append(emp)

        if employees_to_update:
            self.stdout.write(
                f"  HR Employees: {len(employees_to_update)} id_numbers to update"
            )
            if not dry_run:
                with transaction.atomic():
                    Employee.objects.bulk_update(employees_to_update, ["id_number"])
            employee_count = len(employees_to_update)

        # ── 3. user_account_id_number cross-references (within tenant) ─────────
        all_user_id_renames: dict[str, str] = {**student_renames, **employee_renames}

        # Update Student.user_account_id_number
        for old_id in all_user_id_renames:
            stripped_new = _strip(old_id)
            if stripped_new != old_id:
                qs = Student.objects.filter(user_account_id_number=old_id)
                if qs.count() and not dry_run:
                    qs.update(user_account_id_number=stripped_new)

        # Update HR Employee.user_account_id_number
        for old_id in all_user_id_renames:
            stripped_new = _strip(old_id)
            if stripped_new != old_id:
                qs = Employee.objects.filter(user_account_id_number=old_id)
                if qs.count() and not dry_run:
                    qs.update(user_account_id_number=stripped_new)

        # ── 4. Update User.id_number in public schema ──────────────────────────
        all_entity_renames = {**student_renames, **employee_renames}

        if all_entity_renames:
            with schema_context(get_public_schema_name()):
                from users.models import User

                users_to_update = []
                for old_id, new_id in all_entity_renames.items():
                    user = User.objects.filter(id_number=old_id).first()
                    if user:
                        user.id_number = new_id
                        users_to_update.append(user)

                if users_to_update:
                    self.stdout.write(
                        f"  Users (public schema): {len(users_to_update)} id_numbers to update"
                    )
                    if not dry_run:
                        with transaction.atomic():
                            User.objects.bulk_update(users_to_update, ["id_number"])
                    user_count = len(users_to_update)

        return student_count, employee_count, user_count

# Hand-written migration: adds payroll/compensation fields and is_teacher
# to hr_employee for production DBs that were deployed before these fields
# were included in 0001_initial.py.
# Uses SafeAddField (idempotent — tolerates pre-existing columns).

import decimal
from django.db import migrations, models
from django.db.utils import ProgrammingError


class SafeAddField(migrations.AddField):
    """AddField that tolerates a pre-existing column (idempotent)."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        connection = schema_editor.connection
        sid = connection.savepoint()
        try:
            super().database_forwards(app_label, schema_editor, from_state, to_state)
            connection.savepoint_commit(sid)
        except ProgrammingError as exc:
            connection.savepoint_rollback(sid)
            if "already exists" in str(exc).lower() or "duplicate" in str(exc).lower():
                pass
            else:
                raise

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        connection = schema_editor.connection
        sid = connection.savepoint()
        try:
            super().database_backwards(app_label, schema_editor, from_state, to_state)
            connection.savepoint_commit(sid)
        except ProgrammingError:
            connection.savepoint_rollback(sid)


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0005_add_id_number_to_employee"),
    ]

    operations = [
        # ---- is_teacher ---------------------------------------------------
        SafeAddField(
            model_name="employee",
            name="is_teacher",
            field=models.BooleanField(default=False),
        ),
        # ---- Payroll fields -----------------------------------------------
        SafeAddField(
            model_name="employee",
            name="salary_type",
            field=models.CharField(
                choices=[("monthly", "Monthly Salary"), ("hourly", "Hourly Wage")],
                default="monthly",
                max_length=20,
            ),
        ),
        SafeAddField(
            model_name="employee",
            name="basic_salary",
            field=models.DecimalField(
                decimal_places=2,
                default=decimal.Decimal("0.00"),
                help_text="Monthly base for MONTHLY salary types; ignored for HOURLY.",
                max_digits=14,
            ),
        ),
        SafeAddField(
            model_name="employee",
            name="hourly_rate",
            field=models.DecimalField(
                decimal_places=2,
                default=decimal.Decimal("0.00"),
                help_text="Hourly rate; required for HOURLY and used for overtime computation.",
                max_digits=10,
            ),
        ),
        # ---- Banking / tax fields ----------------------------------------
        SafeAddField(
            model_name="employee",
            name="tax_id",
            field=models.CharField(blank=True, default=None, max_length=60, null=True),
        ),
        SafeAddField(
            model_name="employee",
            name="bank_name",
            field=models.CharField(blank=True, default=None, max_length=120, null=True),
        ),
        SafeAddField(
            model_name="employee",
            name="bank_account_number",
            field=models.CharField(blank=True, default=None, max_length=60, null=True),
        ),
        # ---- Other fields that may be missing ----------------------------
        SafeAddField(
            model_name="employee",
            name="national_id",
            field=models.CharField(blank=True, default=None, max_length=100, null=True),
        ),
        SafeAddField(
            model_name="employee",
            name="passport_number",
            field=models.CharField(blank=True, default=None, max_length=100, null=True),
        ),
        SafeAddField(
            model_name="employee",
            name="job_title",
            field=models.CharField(blank=True, default=None, max_length=150, null=True),
        ),
        SafeAddField(
            model_name="employee",
            name="employment_type",
            field=models.CharField(
                choices=[
                    ("full_time", "Full-time"),
                    ("part_time", "Part-time"),
                    ("contract", "Contract"),
                    ("temporary", "Temporary"),
                    ("intern", "Intern"),
                ],
                default="full_time",
                max_length=20,
            ),
        ),
        SafeAddField(
            model_name="employee",
            name="termination_date",
            field=models.DateField(blank=True, default=None, null=True),
        ),
        SafeAddField(
            model_name="employee",
            name="termination_reason",
            field=models.TextField(blank=True, default=None, null=True),
        ),
        SafeAddField(
            model_name="employee",
            name="place_of_birth",
            field=models.CharField(blank=True, default=None, max_length=250, null=True),
        ),
        SafeAddField(
            model_name="employee",
            name="user_account_id_number",
            field=models.CharField(
                blank=True,
                default=None,
                help_text="Loose link to a User.id_number in the public schema.",
                max_length=50,
                null=True,
            ),
        ),
    ]

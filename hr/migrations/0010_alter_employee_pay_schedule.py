import django.db.models.deletion
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
        ("hr", "0009_alter_employee_basic_salary"),
        ("payroll_v2", "0005_payroll_v2_pay_schedules"),
    ]

    operations = [
        SafeAddField(
            model_name="employee",
            name="pay_schedule",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="employees",
                to="payroll_v2.payschedule",
            ),
        ),
    ]

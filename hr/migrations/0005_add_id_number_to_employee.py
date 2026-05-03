# Hand-written migration: adds the id_number column to hr_employee and
# hr_employeedependent if it does not already exist in production.
# The column was present in 0001_initial.py but production was deployed
# before that migration included it, so the column is missing on live DB.

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
        ("hr", "0004_employeespecialization"),
    ]

    operations = [
        SafeAddField(
            model_name="employee",
            name="id_number",
            field=models.CharField(
                blank=True,
                default=None,
                help_text=(
                    "National / government-issued identification number. "
                    "Per-tenant uniqueness is enforced by subclasses where required."
                ),
                max_length=50,
                null=True,
            ),
        ),
        SafeAddField(
            model_name="employeedependent",
            name="id_number",
            field=models.CharField(
                blank=True,
                default=None,
                help_text=(
                    "National / government-issued identification number. "
                    "Per-tenant uniqueness is enforced by subclasses where required."
                ),
                max_length=50,
                null=True,
            ),
        ),
    ]

"""Add a direct ``student`` FK to ``AccountingCashTransaction``.

Until now student payments were only discoverable through the
``AccountingStudentPaymentAllocation`` join table, and the bulk upload
flow did not write that join either — so most uploaded tuition payments
had no link back to the student at all. This migration:

1. Adds a nullable ``student_id`` column on ``accounting_cash_transaction``
   (defensive raw SQL — only adds it when missing, to tolerate drifted
   tenant schemas).
2. Adds a composite index on ``(student_id, transaction_date)`` so the
   per-student payment history stays cheap.
3. Backfills ``student_id`` for existing rows that already have payment
   allocations, so legacy student payments don't lose their link.
4. Registers the ``student`` FK with Django's migration state via
   ``state_operations`` so the model state matches the database without
   re-touching the schema.

The defensive pattern mirrors ``0003_backfill_is_system_managed_columns``
and ``0004_backfill_transaction_type_ledger_columns`` already in use.
"""

import django.db.models.deletion
from django.db import migrations, models


TABLE_NAME = "accounting_cash_transaction"
COLUMN_NAME = "student_id"
INDEX_NAME = "accct_student_txdate_idx"
FK_CONSTRAINT_NAME = "accct_student_id_fk"


def add_student_column(apps, schema_editor):
    """Add the ``student_id`` FK column when it's missing.

    Idempotent and safe to re-run on any schema.
    """
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        existing_tables = set(connection.introspection.table_names(cursor))

    if TABLE_NAME not in existing_tables:
        return
    if "student" not in existing_tables:
        # No target table for the FK on this schema — skip cleanly.
        return

    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(
            cursor, TABLE_NAME
        )

    existing_columns = {col.name for col in description}
    q_table = schema_editor.quote_name(TABLE_NAME)
    q_col = schema_editor.quote_name(COLUMN_NAME)
    q_idx = schema_editor.quote_name(INDEX_NAME)
    q_fk = schema_editor.quote_name(FK_CONSTRAINT_NAME)
    q_student = schema_editor.quote_name("student")

    if COLUMN_NAME not in existing_columns:
        schema_editor.execute(
            f"ALTER TABLE {q_table} ADD COLUMN {q_col} uuid NULL"
        )

    # Add the FK constraint when not already present. Use a stable name so
    # we can probe pg_constraint to decide whether to skip.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM pg_constraint
            WHERE conname = %s
            LIMIT 1
            """,
            [FK_CONSTRAINT_NAME],
        )
        fk_exists = cursor.fetchone() is not None

    if not fk_exists:
        schema_editor.execute(
            f"ALTER TABLE {q_table} "
            f"ADD CONSTRAINT {q_fk} FOREIGN KEY ({q_col}) "
            f"REFERENCES {q_student} (id) ON DELETE SET NULL "
            f"DEFERRABLE INITIALLY DEFERRED"
        )

    # CREATE INDEX IF NOT EXISTS is supported on PG 9.5+, which is well
    # below anything this codebase targets.
    schema_editor.execute(
        f"CREATE INDEX IF NOT EXISTS {q_idx} "
        f"ON {q_table} ({q_col}, {schema_editor.quote_name('transaction_date')})"
    )


def backfill_student_fk(apps, schema_editor):
    """Backfill ``cash_transaction.student_id`` from existing allocations.

    Only fills rows where ``student_id`` is still NULL — anything the
    application has already stamped is left untouched.
    """
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        existing = set(connection.introspection.table_names(cursor))

    required = {
        "accounting_cash_transaction",
        "accounting_student_payment_allocation",
        "accounting_student_bill",
        "student",
    }
    if not required.issubset(existing):
        return

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE accounting_cash_transaction AS ct
            SET student_id = sub.student_id
            FROM (
                SELECT
                    a.cash_transaction_id AS cash_transaction_id,
                    sb.student_id         AS student_id
                FROM accounting_student_payment_allocation a
                JOIN accounting_student_bill sb ON sb.id = a.student_bill_id
                WHERE a.cash_transaction_id IS NOT NULL
                  AND sb.student_id IS NOT NULL
                GROUP BY a.cash_transaction_id, sb.student_id
            ) sub
            WHERE ct.id = sub.cash_transaction_id
              AND ct.student_id IS NULL
            """
        )


def noop_reverse(apps, schema_editor):
    # Intentionally no-op: this migration only repairs drifted schemas
    # and backfills data; we never want to drop the column on rollback.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0004_backfill_transaction_type_ledger_columns"),
        ("students", "0003_student_id_number_max_length"),
    ]

    operations = [
        # 1. Make sure the column / constraint / index physically exist
        #    on this schema, idempotently.
        migrations.RunPython(add_student_column, noop_reverse),

        # 2. Tell Django state about the new field without re-touching the
        #    database (the raw SQL above already did that). Without this,
        #    the ORM wouldn't know how to traverse ``cash_transaction.student``.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="accountingcashtransaction",
                    name="student",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="accounting_cash_transactions",
                        to="students.student",
                        help_text=(
                            "Student paid for, when this transaction is "
                            "a student payment."
                        ),
                    ),
                ),
                migrations.AddIndex(
                    model_name="accountingcashtransaction",
                    index=models.Index(
                        fields=["student", "transaction_date"],
                        name=INDEX_NAME,
                    ),
                ),
            ],
            database_operations=[],
        ),

        # 3. Backfill from the existing allocation chain.
        migrations.RunPython(backfill_student_fk, noop_reverse),
    ]

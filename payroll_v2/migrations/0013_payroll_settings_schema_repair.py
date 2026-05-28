"""Ensure payroll_settings has v2 columns and a single row per tenant."""

from django.db import migrations


def _column_names(schema_editor, table_name: str) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s
            """,
            [table_name],
        )
        return {row[0] for row in cursor.fetchall()}


def repair_payroll_settings(apps, schema_editor):
    connection = schema_editor.connection
    if "payroll_settings" not in set(connection.introspection.table_names()):
        return

    columns = _column_names(schema_editor, "payroll_settings")
    with connection.cursor() as cursor:
        if "show_leave_on_paystub" not in columns:
            cursor.execute(
                """
                ALTER TABLE payroll_settings
                ADD COLUMN show_leave_on_paystub boolean NOT NULL DEFAULT true
                """
            )

    PayrollSettings = apps.get_model("payroll_v2", "PayrollSettings")
    rows = list(PayrollSettings.objects.order_by("created_at", "id"))
    if len(rows) <= 1:
        return

    keeper = rows[0]
    updates: dict[str, object] = {}

    for duplicate in rows[1:]:
        if keeper.transaction_type_id is None and duplicate.transaction_type_id:
            updates["transaction_type_id"] = duplicate.transaction_type_id
        if not keeper.payslip_table_column_labels and duplicate.payslip_table_column_labels:
            updates["payslip_table_column_labels"] = duplicate.payslip_table_column_labels
        duplicate.delete()

    if updates:
        for field, value in updates.items():
            setattr(keeper, field, value)
        keeper.save(update_fields=list(updates.keys()))


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0012_migrate_legacy_pay_schedules"),
    ]

    operations = [
        migrations.RunPython(repair_payroll_settings, migrations.RunPython.noop),
    ]

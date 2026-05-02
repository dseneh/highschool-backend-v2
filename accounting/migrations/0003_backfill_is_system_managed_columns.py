from django.db import migrations


def add_missing_is_system_managed_columns(apps, schema_editor):
    connection = schema_editor.connection

    targets = [
        ("accounting_ledger_account", "is_system_managed"),
        ("accounting_transaction_type", "is_system_managed"),
    ]

    with connection.cursor() as cursor:
        existing_tables = set(connection.introspection.table_names(cursor))

    for table_name, column_name in targets:
        if table_name not in existing_tables:
            continue

        with connection.cursor() as cursor:
            description = connection.introspection.get_table_description(cursor, table_name)

        existing_columns = {col.name for col in description}
        if column_name in existing_columns:
            continue

        q_table = schema_editor.quote_name(table_name)
        q_col = schema_editor.quote_name(column_name)
        schema_editor.execute(
            f"ALTER TABLE {q_table} ADD COLUMN {q_col} boolean NOT NULL DEFAULT false"
        )


def noop_reverse(apps, schema_editor):
    # Intentionally no-op: this migration only repairs drifted schemas.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(add_missing_is_system_managed_columns, noop_reverse),
    ]

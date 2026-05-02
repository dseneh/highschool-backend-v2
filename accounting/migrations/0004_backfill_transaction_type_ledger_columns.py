from django.db import migrations


def add_missing_transaction_type_columns(apps, schema_editor):
    connection = schema_editor.connection
    table_name = "accounting_transaction_type"

    with connection.cursor() as cursor:
        existing_tables = set(connection.introspection.table_names(cursor))

    if table_name not in existing_tables:
        return

    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)

    existing_columns = {col.name for col in description}
    q_table = schema_editor.quote_name(table_name)

    if "auto_manage_ledger_account" not in existing_columns:
        schema_editor.execute(
            f"ALTER TABLE {q_table} ADD COLUMN {schema_editor.quote_name('auto_manage_ledger_account')} boolean NOT NULL DEFAULT false"
        )

    # FK-backed columns can be safely created as nullable UUID columns; this fixes
    # runtime select/query crashes on drifted schemas. Django-managed FK constraints
    # may already exist on healthy databases.
    if "default_ledger_account_id" not in existing_columns:
        schema_editor.execute(
            f"ALTER TABLE {q_table} ADD COLUMN {schema_editor.quote_name('default_ledger_account_id')} uuid NULL"
        )

    if "managed_ledger_account_id" not in existing_columns:
        schema_editor.execute(
            f"ALTER TABLE {q_table} ADD COLUMN {schema_editor.quote_name('managed_ledger_account_id')} uuid NULL"
        )


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0003_backfill_is_system_managed_columns"),
    ]

    operations = [
        migrations.RunPython(add_missing_transaction_type_columns, noop_reverse),
    ]

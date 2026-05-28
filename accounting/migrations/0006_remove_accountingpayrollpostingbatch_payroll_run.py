from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0005_accountingcashtransaction_student"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # payroll_run was removed from 0002 migration state when payroll v1 was deleted.
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE accounting_payroll_posting_batch "
                        "DROP COLUMN IF EXISTS payroll_run_id CASCADE;"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]

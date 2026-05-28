from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0011_leavetype_include_on_paystub"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # tax_rules was removed from 0002 migration state when payroll v1 was deleted.
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP TABLE IF EXISTS hr_employee_tax_rules CASCADE;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]

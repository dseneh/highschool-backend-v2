from django.db import migrations


LEGACY_PAYROLL_V1_TABLES = (
    "payslip",
    "payroll_run_payslip_column_group_member",
    "payroll_run_payslip_column_group",
    "employee_tax_rule_override",
    "tax_amount_rule",
    "payroll_item",
    "payroll_item_type_rule",
    "payroll_item_type",
    "tax_rule",
    "payroll_payslip_column_group",
    "payroll_run",
    "hr_employee_tax_rules",
)


def drop_legacy_payroll_v1_tables(apps, schema_editor):
    connection = schema_editor.connection
    existing = set(connection.introspection.table_names())
    with connection.cursor() as cursor:
        for table in LEGACY_PAYROLL_V1_TABLES:
            if table in existing:
                cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0009_payrollsettings"),
        ("hr", "0012_remove_employee_tax_rules"),
        ("accounting", "0006_remove_accountingpayrollpostingbatch_payroll_run"),
    ]

    operations = [
        migrations.RunPython(drop_legacy_payroll_v1_tables, migrations.RunPython.noop),
    ]

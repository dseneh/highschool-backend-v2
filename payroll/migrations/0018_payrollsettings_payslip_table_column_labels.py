from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0017_item_type_payslip_column_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollsettings",
            name="payslip_table_column_labels",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Optional tenant overrides for standard payslip table column headers, e.g. {"basic": "Base Salary", "tax": "PAYE"}.',
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0013_alter_employeetaxruleoverride_applies_to_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollitemtype",
            name="payslip_table_column_label",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Optional payslip run table column label. Items with the same label are "
                    "summed into one column (display only). Leave blank to exclude from "
                    "dedicated columns."
                ),
                max_length=100,
            ),
        ),
    ]

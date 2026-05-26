from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0002_initial"),
        ("payroll", "0007_payslip_employee_cascade"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollrun",
            name="bank_account",
            field=models.ForeignKey(
                blank=True,
                help_text="Bank/cash account used to disburse this payroll run.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payroll_runs",
                to="accounting.accountingbankaccount",
            ),
        ),
    ]

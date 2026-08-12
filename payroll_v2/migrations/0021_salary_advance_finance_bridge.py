from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0015_bank_rule_notification_trigger_status"),
        ("payroll_v2", "0020_salaryadvance_lifecycle_and_payments"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollsettings",
            name="salary_advance_repayment_ledger_account",
            field=models.ForeignKey(
                blank=True,
                help_text="Ledger account credited when early salary advance repayments are completed in finance.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payroll_settings_salary_advance_repayments",
                to="accounting.accountingledgeraccount",
            ),
        ),
        migrations.AddField(
            model_name="salaryadvancepayment",
            name="finance_transaction",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="salary_advance_payment",
                to="accounting.accountingcashtransaction",
            ),
        ),
    ]

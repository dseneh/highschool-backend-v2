from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0016_accountingbankbalancerule_notification_channel"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountingsettings",
            name="salary_advance_repayment_ledger_account",
            field=models.ForeignKey(
                blank=True,
                help_text="GL account used when early salary advance repayments are posted through Finance.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accounting_settings_salary_advance_repayment",
                to="accounting.accountingledgeraccount",
            ),
        ),
    ]

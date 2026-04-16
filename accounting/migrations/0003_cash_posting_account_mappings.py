import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0002_student_bill_lines_and_concession_bill_link"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountingbankaccount",
            name="ledger_account",
            field=models.ForeignKey(
                blank=True,
                help_text="Ledger cash/bank account used during posting",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bank_accounts",
                to="accounting.accountingledgeraccount",
            ),
        ),
        migrations.AddField(
            model_name="accountingcashtransaction",
            name="ledger_account",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional override account; if empty, use transaction type default",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cash_transactions",
                to="accounting.accountingledgeraccount",
            ),
        ),
        migrations.AddField(
            model_name="accountingtransactiontype",
            name="default_ledger_account",
            field=models.ForeignKey(
                blank=True,
                help_text="Default income/expense ledger account used for auto-posting",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="default_transaction_types",
                to="accounting.accountingledgeraccount",
            ),
        ),
        migrations.AddIndex(
            model_name="accountingcashtransaction",
            index=models.Index(
                fields=["transaction_type", "status"],
                name="accounting__transac_type_status_idx",
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0009_backfill_transfer_journal_links"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountingsettings",
            name="student_refund_account",
            field=models.ForeignKey(
                blank=True,
                help_text="Expense account debited when student refunds are issued.",
                null=True,
                on_delete=models.PROTECT,
                related_name="accounting_settings_student_refund",
                to="accounting.accountingledgeraccount",
            ),
        ),
    ]

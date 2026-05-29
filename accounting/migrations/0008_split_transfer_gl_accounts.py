# Generated manually for split transfer GL mappings

import django.db.models.deletion
from django.db import migrations, models


def copy_transfer_clearing_to_in_out(apps, schema_editor):
    AccountingSettings = apps.get_model("accounting", "AccountingSettings")
    for settings in AccountingSettings.objects.exclude(transfer_clearing_account_id__isnull=True):
        clearing_id = settings.transfer_clearing_account_id
        settings.transfer_in_account_id = clearing_id
        settings.transfer_out_account_id = clearing_id
        settings.save(update_fields=["transfer_in_account_id", "transfer_out_account_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0007_accountingsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountingsettings",
            name="transfer_in_account",
            field=models.ForeignKey(
                blank=True,
                help_text="Asset account used as the counterparty for TRANSFER_IN postings.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accounting_settings_transfer_in",
                to="accounting.accountingledgeraccount",
            ),
        ),
        migrations.AddField(
            model_name="accountingsettings",
            name="transfer_out_account",
            field=models.ForeignKey(
                blank=True,
                help_text="Asset account used as the counterparty for TRANSFER_OUT postings.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accounting_settings_transfer_out",
                to="accounting.accountingledgeraccount",
            ),
        ),
        migrations.RunPython(copy_transfer_clearing_to_in_out, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="accountingsettings",
            name="transfer_clearing_account",
        ),
    ]

from django.db import migrations


def backfill_transfer_journal_links(apps, schema_editor):
    from accounting.services.transfer_posting import backfill_transfer_cash_transaction_journal_links

    backfill_transfer_cash_transaction_journal_links()


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0008_split_transfer_gl_accounts"),
    ]

    operations = [
        migrations.RunPython(backfill_transfer_journal_links, migrations.RunPython.noop),
    ]

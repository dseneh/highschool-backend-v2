from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0012_accountingcashtransaction_rejected_actor_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountingcashtransaction",
            name="notes",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="accountingjournalentry",
            name="notes",
            field=models.TextField(blank=True, null=True),
        ),
    ]

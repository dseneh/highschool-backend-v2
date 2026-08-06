from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0011_accountingcashtransaction_completed_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountingcashtransaction",
            name="rejected_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="accountingcashtransaction",
            name="rejected_by",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0014_accountingsettings_default_expense_bank_account_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountingbankbalancerule",
            name="notification_trigger_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("completed", "Completed"),
                ],
                default="completed",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="accountingrulethresholdstate",
            name="last_notified_event_key",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
    ]
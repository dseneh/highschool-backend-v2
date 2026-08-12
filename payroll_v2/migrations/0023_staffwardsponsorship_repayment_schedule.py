from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0022_payrollsettings_ward_sponsorship_deadline_months"),
    ]

    operations = [
        migrations.AddField(
            model_name="staffwardsponsorship",
            name="repayment_schedule",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="staffwardsponsorship",
            name="repayment_paid_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=16),
        ),
        migrations.AddField(
            model_name="staffwardsponsorship",
            name="repayment_remaining_balance",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=16),
        ),
        migrations.AddField(
            model_name="staffwardsponsorship",
            name="repayment_progress_percent",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=7),
        ),
    ]

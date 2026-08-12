from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0016_payrollsettings_salary_advance_default_installments_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrolldeductionschedule",
            name="schedule_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

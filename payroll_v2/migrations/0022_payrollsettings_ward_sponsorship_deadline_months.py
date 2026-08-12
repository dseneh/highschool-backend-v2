from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0021_salary_advance_finance_bridge"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollsettings",
            name="ward_sponsorship_application_deadline_months",
            field=models.PositiveSmallIntegerField(
                default=3,
                help_text="How many months from the academic year start employees can submit ward sponsorship requests.",
            ),
        ),
    ]

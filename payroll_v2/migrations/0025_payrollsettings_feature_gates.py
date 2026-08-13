from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payroll_v2", "0024_staffwardsponsorship_student_allocation"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollsettings",
            name="allow_salary_advance",
            field=models.BooleanField(
                default=False,
                help_text="When enabled, salary advance requests and actions are available to this tenant.",
            ),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="allow_ward_sponsorship",
            field=models.BooleanField(
                default=False,
                help_text="When enabled, staff ward sponsorship requests and actions are available to this tenant.",
            ),
        ),
    ]
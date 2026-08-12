from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0023_staffwardsponsorship_repayment_schedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="staffwardsponsorship",
            name="student_allocation",
            field=models.JSONField(blank=True, default=list),
        ),
    ]

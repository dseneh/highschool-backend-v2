from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0017_payrolldeductionschedule_schedule_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeepayrollitem",
            name="source_id",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="employeepayrollitem",
            name="source_type",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="salaryadvance",
            name="amount_paid",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=16),
        ),
        migrations.AddIndex(
            model_name="employeepayrollitem",
            index=models.Index(fields=["source_type", "source_id"], name="payroll_v2__source__68cce8_idx"),
        ),
    ]

from decimal import Decimal

from django.db import migrations, models


def backfill_compensation_annual_salary(apps, schema_editor):
    EmployeeCompensation = apps.get_model("payroll_v2", "EmployeeCompensation")
    PaySchedule = apps.get_model("payroll_v2", "PaySchedule")

    def periods_per_year(schedule):
        if schedule is None:
            return Decimal("12")
        frequency = getattr(schedule, "frequency", "monthly")
        if frequency == "weekly":
            return Decimal("52")
        if frequency == "biweekly":
            return Decimal("26")
        return Decimal("12")

    batch = []
    for record in EmployeeCompensation.objects.select_related("employee").iterator():
        employee = record.employee
        if record.pay_type == "hourly":
            annual = Decimal("0.00")
        else:
            period_amount = record.base_amount or Decimal("0.00")
            if record.pay_type == "daily":
                period_amount = record.daily_rate or record.base_amount or Decimal("0.00")
            schedule = None
            if employee.pay_schedule_id:
                schedule = PaySchedule.objects.filter(id=employee.pay_schedule_id).first()
            annual = (Decimal(period_amount or 0) * periods_per_year(schedule)).quantize(Decimal("0.01"))
        record.annual_salary = annual
        batch.append(record)
        if len(batch) >= 500:
            EmployeeCompensation.objects.bulk_update(batch, ["annual_salary"])
            batch = []
    if batch:
        EmployeeCompensation.objects.bulk_update(batch, ["annual_salary"])


class Migration(migrations.Migration):
    dependencies = [
        ("payroll_v2", "0006_rename_payroll_v2__pay_sch_6f0a2d_idx_payroll_v2__pay_sch_188ad2_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeecompensation",
            name="annual_salary",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Annualized pay from base amount and the employee pay schedule frequency.",
                max_digits=14,
            ),
        ),
        migrations.RunPython(backfill_compensation_annual_salary, migrations.RunPython.noop),
    ]

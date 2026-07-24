from decimal import Decimal

from django.db import migrations, models


def _periods_per_year(schedule) -> Decimal:
    if schedule is None:
        return Decimal("12")
    frequency = getattr(schedule, "frequency", None) or "monthly"
    if frequency == "weekly":
        return Decimal("52")
    if frequency == "biweekly":
        return Decimal("26")
    return Decimal("12")


def backfill_annual_salary(apps, schema_editor):
    Employee = apps.get_model("hr", "Employee")
    batch: list = []
    for employee in Employee.objects.iterator():
        if employee.salary_type == "hourly":
            employee.annual_salary = Decimal("0.00")
        else:
            employee.annual_salary = (
                Decimal(employee.basic_salary or 0)
                * _periods_per_year(None)
            ).quantize(Decimal("0.01"))
        batch.append(employee)
        if len(batch) >= 500:
            Employee.objects.bulk_update(batch, ["annual_salary"])
            batch = []
    if batch:
        Employee.objects.bulk_update(batch, ["annual_salary"])


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0007_employee_teacher_assignments"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="annual_salary",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Computed from basic_salary and pay schedule frequency; used for annual tax/item brackets.",
                max_digits=14,
            ),
        ),
        migrations.RunPython(backfill_annual_salary, migrations.RunPython.noop),
    ]

from decimal import Decimal

from django.db import migrations, models


def backfill_annual_salary(apps, schema_editor):
    Employee = apps.get_model("hr", "Employee")
    batch: list = []
    # pay_schedule is added in hr.0010, which runs after this migration.
    # Use monthly periods for any pre-existing rows; new tenant schemas are empty here.
    for employee in Employee.objects.iterator():
        if employee.salary_type == "hourly":
            employee.annual_salary = Decimal("0.00")
        else:
            employee.annual_salary = (
                Decimal(employee.basic_salary or 0) * Decimal("12")
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

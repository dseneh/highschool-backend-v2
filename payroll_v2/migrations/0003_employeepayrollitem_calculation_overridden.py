from decimal import Decimal

from django.db import migrations, models


def mark_existing_custom_calculations(apps, schema_editor):
    EmployeePayrollItem = apps.get_model("payroll_v2", "EmployeePayrollItem")
    for assignment in EmployeePayrollItem.objects.all().iterator():
        if (
            assignment.calculation_type != "flat"
            or (assignment.value or Decimal("0")) != Decimal("0")
            or (assignment.formula or "").strip()
            or assignment.calculation_limit is not None
        ):
            assignment.calculation_overridden = True
            assignment.save(update_fields=["calculation_overridden"])


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeepayrollitem",
            name="calculation_overridden",
            field=models.BooleanField(
                default=False,
                help_text="When true, employee-specific calculation replaces catalog rules for this item.",
            ),
        ),
        migrations.RunPython(mark_existing_custom_calculations, migrations.RunPython.noop),
    ]

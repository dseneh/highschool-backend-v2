from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0018_salary_advance_amount_paid_and_employee_item_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollsettings",
            name="maximum_salary_advance_deduction_percent",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("20.0000"),
                help_text="Maximum share of gross salary that can go to salary advance deduction in one payroll.",
                max_digits=7,
            ),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="maximum_ward_sponsorship_deduction_percent",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("40.0000"),
                help_text="Maximum share of gross salary that can go to ward sponsorship deduction in one payroll.",
                max_digits=7,
            ),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="minimum_take_home_pay_percent",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("30.0000"),
                help_text="Minimum gross salary share that must remain as take-home pay after deductions.",
                max_digits=7,
            ),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="tax_reserve_percent",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("20.0000"),
                help_text="Minimum gross salary share reserved to protect tax obligations before new deductions.",
                max_digits=7,
            ),
        ),
    ]

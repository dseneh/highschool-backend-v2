from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0011_payroll_adjustments_and_taxable_flag"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollitem",
            name="override_applies_to",
            field=models.CharField(
                blank=True,
                choices=[("gross", "Gross Pay"), ("basic", "Basic Salary")],
                default=None,
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="payrollitem",
            name="override_calculation_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("flat", "Flat Amount"),
                    ("percentage", "Percentage"),
                    ("formula", "Formula"),
                ],
                default=None,
                help_text="When set, replaces catalog bracket rules for this employee assignment.",
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="payrollitem",
            name="override_formula",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Python expression when override_calculation_type=formula.",
            ),
        ),
        migrations.AddField(
            model_name="payrollitem",
            name="override_value",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                default=None,
                help_text="Flat amount or percentage depending on override_calculation_type.",
                max_digits=14,
                null=True,
            ),
        ),
    ]

import uuid

import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0010_alter_payrollsettings_created_by_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollitemtype",
            name="is_taxable",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "For allowances and adjustments: when false, the amount is excluded from "
                    "gross/tax and added to take-home pay after net is calculated."
                ),
            ),
        ),
        migrations.AddField(
            model_name="payslip",
            name="adjustments",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text=(
                    "Non-taxable additions applied after net pay (reimbursements, adjustments, etc.)."
                ),
                max_digits=14,
            ),
        ),
        migrations.AlterField(
            model_name="payrollitem",
            name="item_type",
            field=models.CharField(
                choices=[
                    ("allowance", "Allowance"),
                    ("adjustment", "Adjustment"),
                    ("deduction", "Deduction"),
                ],
                default="allowance",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="payrollitemtype",
            name="item_type",
            field=models.CharField(
                choices=[
                    ("allowance", "Allowance"),
                    ("adjustment", "Adjustment"),
                    ("deduction", "Deduction"),
                ],
                default="allowance",
                max_length=20,
            ),
        ),
    ]

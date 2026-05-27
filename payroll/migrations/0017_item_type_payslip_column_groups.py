# Generated manually for item-type payslip column groups.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0016_payroll_run_payslip_column_groups"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PayrollPayslipColumnGroup",
            fields=[
                ("id", models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("label", models.CharField(max_length=100)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "payroll_payslip_column_group",
                "ordering": ["sort_order", "label"],
            },
        ),
        migrations.AddConstraint(
            model_name="payrollpayslipcolumngroup",
            constraint=models.UniqueConstraint(
                fields=("label",),
                name="payroll_uniq_payslip_column_group_label_per_tenant",
            ),
        ),
        migrations.AddField(
            model_name="payrollitemtype",
            name="payslip_column_group",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional payslip table column group. Item types in the same group are summed into one column when payslips are generated. Leave blank for a standalone column.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="item_types",
                to="payroll.payrollpayslipcolumngroup",
            ),
        ),
        migrations.RemoveField(
            model_name="payrollrun",
            name="payslip_columns_enabled",
        ),
        migrations.DeleteModel(
            name="PayrollRunPayslipColumnGroupMember",
        ),
        migrations.DeleteModel(
            name="PayrollRunPayslipColumnGroup",
        ),
    ]

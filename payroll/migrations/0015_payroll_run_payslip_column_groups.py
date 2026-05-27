from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0014_payrollitemtype_payslip_table_column_label"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollrun",
            name="payslip_columns_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When enabled, payslip tables on this run show grouped or standalone "
                    "columns based on the run's payslip column group configuration."
                ),
            ),
        ),
        migrations.CreateModel(
            name="PayrollRunPayslipColumnGroup",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.UUIDField(blank=True, null=True)),
                ("updated_by", models.UUIDField(blank=True, null=True)),
                ("label", models.CharField(max_length=100)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                (
                    "payroll_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payslip_column_groups",
                        to="payroll.payrollrun",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_run_payslip_column_group",
                "ordering": ["sort_order", "label"],
            },
        ),
        migrations.CreateModel(
            name="PayrollRunPayslipColumnGroupMember",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.UUIDField(blank=True, null=True)),
                ("updated_by", models.UUIDField(blank=True, null=True)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="members",
                        to="payroll.payrollrunpayslipcolumngroup",
                    ),
                ),
                (
                    "item_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payslip_column_group_memberships",
                        to="payroll.payrollitemtype",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_run_payslip_column_group_member",
            },
        ),
        migrations.AddConstraint(
            model_name="payrollrunpayslipcolumngroupmember",
            constraint=models.UniqueConstraint(
                fields=("group", "item_type"),
                name="payroll_uniq_payslip_column_group_member",
            ),
        ),
        migrations.RemoveField(
            model_name="payrollitemtype",
            name="payslip_table_column_label",
        ),
    ]

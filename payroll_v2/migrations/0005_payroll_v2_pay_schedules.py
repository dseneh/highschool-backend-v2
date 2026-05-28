from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def copy_pay_schedules_forward(apps, schema_editor):
    return


def copy_payroll_periods_forward(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0005_accountingcashtransaction_student"),
        ("payroll_v2", "0004_payrollrunrecord_pay_schedule"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaySchedule",
            fields=[
                ("id", models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=150)),
                (
                    "frequency",
                    models.CharField(
                        choices=[("monthly", "Monthly"), ("biweekly", "Bi-Weekly"), ("weekly", "Weekly")],
                        default="monthly",
                        max_length=20,
                    ),
                ),
                (
                    "anchor_date",
                    models.DateField(
                        help_text="Reference date — the first period starts here; subsequent periods step from it."
                    ),
                ),
                ("payment_day_offset", models.PositiveSmallIntegerField(default=0, help_text="Days after period_end when payment is made.")),
                ("overtime_multiplier", models.DecimalField(decimal_places=2, default=Decimal("1.50"), max_digits=4)),
                ("is_default", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_created",
                        to="users.user",
                    ),
                ),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payroll_v2_pay_schedules",
                        to="accounting.accountingcurrency",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_updated",
                        to="users.user",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_v2_pay_schedule",
                "ordering": ["-is_default", "name"],
            },
        ),
        migrations.CreateModel(
            name="PayrollPeriod",
            fields=[
                ("id", models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=150)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("payment_date", models.DateField()),
                ("is_closed", models.BooleanField(default=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_created",
                        to="users.user",
                    ),
                ),
                (
                    "schedule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="periods",
                        to="payroll_v2.payschedule",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_updated",
                        to="users.user",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_v2_payroll_period",
                "ordering": ["-start_date"],
            },
        ),
        migrations.AddConstraint(
            model_name="payschedule",
            constraint=models.UniqueConstraint(fields=("name",), name="payroll_v2_uniq_pay_schedule_name"),
        ),
        migrations.AddConstraint(
            model_name="payschedule",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_default", True)),
                fields=("is_default",),
                name="payroll_v2_uniq_default_pay_schedule",
            ),
        ),
        migrations.AddConstraint(
            model_name="payrollperiod",
            constraint=models.UniqueConstraint(
                fields=("schedule", "start_date", "end_date"),
                name="payroll_v2_uniq_period_per_schedule",
            ),
        ),
        migrations.RunPython(copy_pay_schedules_forward, migrations.RunPython.noop),
        migrations.RunPython(copy_payroll_periods_forward, migrations.RunPython.noop),
        migrations.AddField(
            model_name="payrollrunrecord",
            name="pay_schedule",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payroll_runs",
                to="payroll_v2.payschedule",
            ),
        ),
        migrations.AddField(
            model_name="payrollrunrecord",
            name="payroll_period",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payroll_runs",
                to="payroll_v2.payrollperiod",
            ),
        ),
        migrations.AddIndex(
            model_name="payrollrunrecord",
            index=models.Index(fields=["pay_schedule"], name="payroll_v2__pay_sch_6f0a2d_idx"),
        ),
    ]

import uuid

import django.db.models.deletion
from django.db import migrations, models


def ensure_payroll_settings_table(apps, schema_editor):
    if "payroll_settings" in schema_editor.connection.introspection.table_names():
        return

    # PayrollSettings is introduced by this same SeparateDatabaseAndState
    # migration, so it is not reliably available from the historical app
    # registry passed to RunPython.
    from payroll_v2.models import PayrollSettings

    schema_editor.create_model(PayrollSettings)


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0008_total_deductions_include_tax"),
        ("accounting", "0005_accountingcashtransaction_student"),
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="PayrollSettings",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=uuid.uuid4,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("active", models.BooleanField(default=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "created_by",
                            models.ForeignKey(
                                blank=True,
                                default=None,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="created_payrollsettings_set",
                                to="users.user",
                                to_field="id",
                            ),
                        ),
                        (
                            "updated_by",
                            models.ForeignKey(
                                blank=True,
                                default=None,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="updated_payrollsettings_set",
                                to="users.user",
                                to_field="id",
                            ),
                        ),
                        (
                            "payslip_table_column_labels",
                            models.JSONField(
                                blank=True,
                                default=dict,
                                help_text='Optional tenant overrides for standard payslip table column headers, e.g. {"basic": "Base Salary", "tax": "PAYE"}.',
                            ),
                        ),
                        (
                            "show_leave_on_paystub",
                            models.BooleanField(
                                default=True,
                                help_text="When enabled, eligible leave balances appear on employee paystubs.",
                            ),
                        ),
                        (
                            "transaction_type",
                            models.ForeignKey(
                                blank=True,
                                help_text="Expense transaction type used when posting payroll cash disbursements.",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="payroll_settings",
                                to="accounting.accountingtransactiontype",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "Payroll Settings",
                        "verbose_name_plural": "Payroll Settings",
                        "db_table": "payroll_settings",
                    },
                ),
            ],
            database_operations=[
                migrations.RunPython(ensure_payroll_settings_table, migrations.RunPython.noop),
            ],
        ),
    ]

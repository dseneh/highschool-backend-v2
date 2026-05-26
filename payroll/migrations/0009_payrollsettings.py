import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0005_accountingcashtransaction_student"),
        ("payroll", "0008_payrollrun_bank_account"),
        ("users", "0001_initial"),
    ]

    operations = [
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
    ]

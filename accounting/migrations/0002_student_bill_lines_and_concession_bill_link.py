# Generated manually to avoid local DB migration-history inconsistency.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountingStudentBillLine",
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
                        related_name="created_%(class)s_set",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_%(class)s_set",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("description", models.CharField(blank=True, max_length=255)),
                ("quantity", models.DecimalField(decimal_places=2, default=1, max_digits=10)),
                ("unit_amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("line_amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("line_sequence", models.PositiveIntegerField(default=1)),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="accounting.accountingcurrency",
                    ),
                ),
                (
                    "fee_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bill_lines",
                        to="accounting.accountingfeeitem",
                    ),
                ),
                (
                    "student_bill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="accounting.accountingstudentbill",
                    ),
                ),
            ],
            options={
                "verbose_name": "Student Bill Line",
                "verbose_name_plural": "Student Bill Lines",
                "db_table": "accounting_student_bill_line",
                "ordering": ["student_bill", "line_sequence"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("student_bill", "line_sequence"),
                        name="unique_student_bill_line_sequence",
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="accountingconcession",
            name="student_bill",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional explicit bill this concession was applied to",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="concessions",
                to="accounting.accountingstudentbill",
            ),
        ),
    ]

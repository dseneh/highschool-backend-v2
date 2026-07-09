from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_tenant_billing_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="BillingSeat",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("student_id", models.UUIDField(blank=True, null=True)),
                ("enrollment_id", models.UUIDField()),
                ("academic_year_id", models.UUIDField()),
                ("activated_at", models.DateTimeField()),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("void_reason", models.CharField(blank=True, default="", max_length=64)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="billing_seats",
                        to="core.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "billing_seat",
                "indexes": [
                    models.Index(fields=["tenant", "academic_year_id", "voided_at"], name="billing_seat_tenant_year_void_idx"),
                    models.Index(fields=["tenant", "enrollment_id"], name="billing_seat_tenant_enroll_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="billingseat",
            constraint=models.UniqueConstraint(
                fields=("tenant", "enrollment_id", "academic_year_id"),
                name="billing_seat_unique_enrollment_year",
            ),
        ),
    ]

from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def migrate_salary_advance_states(apps, schema_editor):
    SalaryAdvance = apps.get_model("payroll_v2", "SalaryAdvance")

    SalaryAdvance.objects.filter(status="pending").update(status="submitted")
    SalaryAdvance.objects.filter(status="active").update(status="completed")

    for advance in SalaryAdvance.objects.all().iterator():
        amount_paid = Decimal(str(getattr(advance, "amount_paid", 0) or 0))
        remaining_balance = Decimal(str(getattr(advance, "remaining_balance", 0) or 0))
        status = getattr(advance, "status", "draft")

        if remaining_balance <= Decimal("0.00") and amount_paid > Decimal("0.00"):
            repayment_status = "paid"
        elif amount_paid > Decimal("0.00"):
            repayment_status = "in_progress"
        else:
            repayment_status = "not_started"

        updates = {"repayment_status": repayment_status}
        if status == "completed" and getattr(advance, "completed_at", None) is None:
            updates["completed_at"] = getattr(advance, "approved_at", None) or django.utils.timezone.now()

        SalaryAdvance.objects.filter(pk=advance.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_v2", "0019_payrollsettings_obligation_percentage_rules"),
    ]

    operations = [
        migrations.CreateModel(
            name="SalaryAdvancePayment",
            fields=[
                ("id", models.UUIDField(default=__import__("uuid").uuid4, editable=False, primary_key=True, serialize=False)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("payment_date", models.DateField(default=django.utils.timezone.now)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("payment_method", models.CharField(choices=[("cash", "Cash"), ("check", "Check"), ("bank_transfer", "Bank Transfer"), ("mobile_money", "Mobile Money"), ("other", "Other")], default="other", max_length=30)),
                ("reference", models.CharField(blank=True, max_length=150)),
                ("notes", models.TextField(blank=True)),
                ("created_by", models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_%(class)s_set", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_%(class)s_set", to=settings.AUTH_USER_MODEL)),
                ("salary_advance", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments", to="payroll_v2.salaryadvance")),
            ],
            options={
                "db_table": "payroll_v2_salary_advance_payment",
                "ordering": ["-payment_date", "-created_at"],
            },
        ),
        migrations.AddField(
            model_name="salaryadvance",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="salaryadvance",
            name="cancellation_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="salaryadvance",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="salaryadvance",
            name="repayment_status",
            field=models.CharField(choices=[("not_started", "Not Started"), ("in_progress", "In Progress"), ("paid", "Paid")], default="not_started", max_length=20),
        ),
        migrations.AddField(
            model_name="salaryadvance",
            name="cancelled_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cancelled_salary_advances", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="salaryadvance",
            name="completed_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="completed_salary_advances", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="salaryadvance",
            name="status",
            field=models.CharField(choices=[("draft", "Draft"), ("submitted", "Submitted"), ("approved", "Approved"), ("completed", "Completed"), ("rejected", "Rejected"), ("cancelled", "Cancelled")], default="draft", max_length=20),
        ),
        migrations.AddIndex(
            model_name="salaryadvancepayment",
            index=models.Index(fields=["salary_advance", "payment_date"], name="payroll_v2__salary__256aa0_idx"),
        ),
        migrations.RunPython(migrate_salary_advance_states, migrations.RunPython.noop),
    ]
from decimal import Decimal

from django.db import migrations


def recalculate_payroll_v2_deduction_totals(apps, schema_editor):
    PayrollEmployeeItem = apps.get_model("payroll_v2", "PayrollEmployeeItem")
    PayrollLineItem = apps.get_model("payroll_v2", "PayrollLineItem")
    PayrollRunRecord = apps.get_model("payroll_v2", "PayrollRunRecord")

    for item in PayrollEmployeeItem.objects.iterator(chunk_size=500):
        lines = PayrollLineItem.objects.filter(payroll_employee_item_id=item.pk)
        other_deductions = sum(
            (line.amount for line in lines if line.line_type == "deduction"),
            Decimal("0.00"),
        )
        total_tax = sum(
            (line.amount for line in lines if line.line_type == "tax"),
            Decimal("0.00"),
        )
        total_deductions = other_deductions + total_tax
        total_benefits = sum(
            (line.amount for line in lines if line.line_type == "benefit"),
            Decimal("0.00"),
        )
        total_reimbursements = sum(
            (line.amount for line in lines if line.line_type == "reimbursement"),
            Decimal("0.00"),
        )
        gross_pay = sum(
            (line.amount for line in lines if line.line_type == "earning"),
            Decimal("0.00"),
        )
        net_pay = gross_pay + total_reimbursements - total_deductions - total_benefits
        PayrollEmployeeItem.objects.filter(pk=item.pk).update(
            total_tax=total_tax,
            total_deductions=total_deductions,
            gross_pay=gross_pay,
            net_pay=net_pay,
        )

    for run in PayrollRunRecord.objects.iterator(chunk_size=200):
        employee_items = PayrollEmployeeItem.objects.filter(payroll_id=run.pk)
        PayrollRunRecord.objects.filter(pk=run.pk).update(
            gross_pay_total=sum((i.gross_pay for i in employee_items), Decimal("0.00")),
            deduction_total=sum((i.total_deductions for i in employee_items), Decimal("0.00")),
            tax_total=sum((i.total_tax for i in employee_items), Decimal("0.00")),
            benefit_total=sum((i.total_benefits for i in employee_items), Decimal("0.00")),
            reimbursement_total=sum((i.total_reimbursements for i in employee_items), Decimal("0.00")),
            net_pay_total=sum((i.net_pay for i in employee_items), Decimal("0.00")),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll_v2", "0007_employeecompensation_annual_salary"),
    ]

    operations = [
        migrations.RunPython(recalculate_payroll_v2_deduction_totals, migrations.RunPython.noop),
    ]

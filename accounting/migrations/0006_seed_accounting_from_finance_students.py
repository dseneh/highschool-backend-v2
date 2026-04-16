from __future__ import annotations

from decimal import Decimal

from django.db import migrations
from django.utils import timezone
from django.utils.text import slugify


def _unique_code(base: str, used_codes: set[str], max_len: int = 50) -> str:
    seed = slugify(base or "item").replace("-", "_").upper()
    seed = (seed or "ITEM")[:max_len]

    candidate = seed
    idx = 1
    while candidate in used_codes:
        suffix = f"_{idx}"
        candidate = f"{seed[: max_len - len(suffix)]}{suffix}"
        idx += 1

    used_codes.add(candidate)
    return candidate


def _safe_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def forward_seed_accounting(apps, schema_editor):
    from django.db.models import Sum

    AccountingCurrency = apps.get_model("accounting", "AccountingCurrency")
    AccountingPaymentMethod = apps.get_model("accounting", "AccountingPaymentMethod")
    AccountingTransactionType = apps.get_model("accounting", "AccountingTransactionType")
    AccountingBankAccount = apps.get_model("accounting", "AccountingBankAccount")
    AccountingCashTransaction = apps.get_model("accounting", "AccountingCashTransaction")

    AccountingFeeItem = apps.get_model("accounting", "AccountingFeeItem")
    AccountingFeeRate = apps.get_model("accounting", "AccountingFeeRate")
    AccountingStudentBill = apps.get_model("accounting", "AccountingStudentBill")
    AccountingStudentBillLine = apps.get_model("accounting", "AccountingStudentBillLine")
    AccountingConcession = apps.get_model("accounting", "AccountingConcession")
    AccountingInstallmentPlan = apps.get_model("accounting", "AccountingInstallmentPlan")
    AccountingInstallmentLine = apps.get_model("accounting", "AccountingInstallmentLine")

    FinanceCurrency = apps.get_model("finance", "Currency")
    FinancePaymentMethod = apps.get_model("finance", "PaymentMethod")
    FinanceTransactionType = apps.get_model("finance", "TransactionType")
    FinanceBankAccount = apps.get_model("finance", "BankAccount")
    FinanceTransaction = apps.get_model("finance", "Transaction")
    FinanceGeneralFeeList = apps.get_model("finance", "GeneralFeeList")
    FinancePaymentInstallment = apps.get_model("finance", "PaymentInstallment")

    StudentEnrollmentBill = apps.get_model("students", "StudentEnrollmentBill")
    StudentConcession = apps.get_model("students", "StudentConcession")
    Enrollment = apps.get_model("students", "Enrollment")

    now = timezone.now()

    # 1) Currency bootstrap
    currency_map = {}
    accounting_codes = set(
        AccountingCurrency.objects.values_list("code", flat=True)
    )

    finance_currencies = list(FinanceCurrency.objects.all().order_by("id"))
    if finance_currencies:
        first_currency_id = str(finance_currencies[0].id)
        for finance_currency in finance_currencies:
            code = (finance_currency.code or "CUR").upper()[:3]
            base_code = code
            idx = 1
            while code in accounting_codes:
                code = f"{base_code[:2]}{idx % 10}"
                idx += 1
            accounting_codes.add(code)

            accounting_currency, _ = AccountingCurrency.objects.get_or_create(
                code=code,
                defaults={
                    "name": finance_currency.name or code,
                    "symbol": finance_currency.symbol or code,
                    "is_base_currency": str(finance_currency.id) == first_currency_id,
                    "is_active": bool(getattr(finance_currency, "active", True)),
                    "decimal_places": 2,
                    "created_at": now,
                    "updated_at": now,
                    "active": True,
                },
            )
            currency_map[str(finance_currency.id)] = accounting_currency

    base_currency = AccountingCurrency.objects.order_by("-is_base_currency", "created_at").first()
    if base_currency is None:
        base_currency = AccountingCurrency.objects.create(
            name="Default Currency",
            code="USD",
            symbol="$",
            is_base_currency=True,
            is_active=True,
            decimal_places=2,
            created_at=now,
            updated_at=now,
            active=True,
        )

    # 2) Payment methods
    payment_method_map = {}
    pm_codes = set(AccountingPaymentMethod.objects.values_list("code", flat=True))
    for finance_pm in FinancePaymentMethod.objects.all().order_by("name"):
        code = _unique_code(finance_pm.name or "payment_method", pm_codes)
        accounting_pm, _ = AccountingPaymentMethod.objects.get_or_create(
            name=finance_pm.name,
            defaults={
                "code": code,
                "description": getattr(finance_pm, "description", None),
                "is_active": bool(getattr(finance_pm, "active", True)),
                "created_at": now,
                "updated_at": now,
                "active": True,
            },
        )
        payment_method_map[str(finance_pm.id)] = accounting_pm

    # 3) Transaction types
    tx_type_map = {}
    tx_codes = set(AccountingTransactionType.objects.values_list("code", flat=True))
    for finance_tt in FinanceTransactionType.objects.all().order_by("name"):
        category = "income" if finance_tt.type == "income" else "expense"
        code_seed = finance_tt.type_code or finance_tt.name or "transaction_type"
        code = _unique_code(code_seed, tx_codes)
        accounting_tt, _ = AccountingTransactionType.objects.get_or_create(
            name=finance_tt.name,
            transaction_category=category,
            defaults={
                "code": code,
                "description": getattr(finance_tt, "description", None),
                "is_active": bool(not getattr(finance_tt, "is_hidden", False)) and bool(getattr(finance_tt, "active", True)),
                "created_at": now,
                "updated_at": now,
                "active": True,
            },
        )
        tx_type_map[str(finance_tt.id)] = accounting_tt

    # 4) Bank accounts
    bank_account_map = {}
    for finance_ba in FinanceBankAccount.objects.all().order_by("number"):
        account_number = finance_ba.number
        if AccountingBankAccount.objects.filter(account_number=account_number).exists():
            account_number = f"{account_number}-A"

        accounting_ba, _ = AccountingBankAccount.objects.get_or_create(
            account_name=finance_ba.name,
            defaults={
                "account_number": account_number,
                "bank_name": finance_ba.bank_number or "",
                "account_type": "checking",
                "currency": base_currency,
                "opening_balance": Decimal("0"),
                "current_balance": Decimal("0"),
                "status": "active",
                "description": getattr(finance_ba, "description", None),
                "created_at": now,
                "updated_at": now,
                "active": True,
            },
        )
        bank_account_map[str(finance_ba.id)] = accounting_ba

    # 5) Fee items and rates
    fee_item_map = {}
    fee_codes = set(AccountingFeeItem.objects.values_list("code", flat=True))

    all_academic_years = list(
        apps.get_model("academics", "AcademicYear").objects.all().order_by("start_date")
    )

    for fee in FinanceGeneralFeeList.objects.all().order_by("name"):
        target = (fee.student_target or "").lower()
        category = "tuition" if "tuition" in target else "general"
        code = _unique_code(fee.name or "fee_item", fee_codes)

        accounting_fee, _ = AccountingFeeItem.objects.get_or_create(
            name=fee.name,
            defaults={
                "code": code,
                "category": category,
                "description": getattr(fee, "description", None),
                "is_active": bool(getattr(fee, "active", True)),
                "created_at": now,
                "updated_at": now,
                "active": True,
            },
        )
        fee_item_map[str(fee.id)] = accounting_fee

        for year in all_academic_years:
            AccountingFeeRate.objects.get_or_create(
                fee_item=accounting_fee,
                academic_year=year,
                grade_level=None,
                student_category=fee.student_target or "",
                defaults={
                    "amount": _safe_decimal(fee.amount),
                    "currency": base_currency,
                    "created_at": now,
                    "updated_at": now,
                    "active": True,
                },
            )

    # 6) Installment plans from finance installments
    installment_plan_map = {}
    for installment in FinancePaymentInstallment.objects.select_related("academic_year").all().order_by("academic_year", "sequence"):
        academic_year = installment.academic_year
        plan = installment_plan_map.get(str(academic_year.id))
        if plan is None:
            plan, _ = AccountingInstallmentPlan.objects.get_or_create(
                academic_year=academic_year,
                name=f"Migrated Plan {getattr(academic_year, 'name', '')}".strip(),
                defaults={
                    "description": "Auto-generated from finance payment installments",
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                    "active": True,
                },
            )
            installment_plan_map[str(academic_year.id)] = plan

        sequence = installment.sequence or 1
        AccountingInstallmentLine.objects.get_or_create(
            installment_plan=plan,
            sequence=sequence,
            defaults={
                "name": installment.name or f"Installment {sequence}",
                "due_date": installment.due_date,
                "percentage": _safe_decimal(installment.value),
                "grace_days": 0,
                "created_at": now,
                "updated_at": now,
                "active": True,
            },
        )

    # 7) Student bills + lines (group old enrollment bill rows into one accounting bill per enrollment)
    accounting_bill_map = {}

    enrollment_bills = (
        StudentEnrollmentBill.objects.select_related("enrollment", "enrollment__student", "enrollment__academic_year", "enrollment__grade_level")
        .all()
        .order_by("enrollment", "created_at")
    )

    from collections import defaultdict

    grouped = defaultdict(list)
    for row in enrollment_bills:
        grouped[str(row.enrollment_id)].append(row)

    approved_income_by_student_year = defaultdict(Decimal)
    for tx in FinanceTransaction.objects.select_related("student", "academic_year", "type").filter(status="approved", type__type="income"):
        if tx.student_id and tx.academic_year_id:
            key = (str(tx.student_id), str(tx.academic_year_id))
            approved_income_by_student_year[key] += abs(_safe_decimal(tx.amount))

    for enrollment_id, rows in grouped.items():
        enrollment = rows[0].enrollment
        student = enrollment.student
        academic_year = enrollment.academic_year
        grade_level = enrollment.grade_level

        gross_amount = sum((_safe_decimal(r.amount) for r in rows), Decimal("0"))

        concession_total = _safe_decimal(
            StudentConcession.objects.filter(
                student=student,
                academic_year=academic_year,
                active=True,
            ).aggregate(total=Sum("amount"))["total"]
        )
        if concession_total < 0:
            concession_total = Decimal("0")

        net_amount = gross_amount - concession_total
        if net_amount < 0:
            net_amount = Decimal("0")

        paid_amount = approved_income_by_student_year.get((str(student.id), str(academic_year.id)), Decimal("0"))
        if paid_amount > net_amount:
            paid_amount = net_amount

        outstanding = net_amount - paid_amount

        due_date = getattr(academic_year, "end_date", None) or timezone.now().date()
        bill_date = timezone.now().date()

        status = "issued"
        if outstanding <= Decimal("0"):
            status = "paid"
        elif due_date and due_date < timezone.now().date():
            status = "overdue"

        accounting_bill, _ = AccountingStudentBill.objects.get_or_create(
            enrollment=enrollment,
            academic_year=academic_year,
            student=student,
            grade_level=grade_level,
            defaults={
                "bill_date": bill_date,
                "due_date": due_date,
                "gross_amount": gross_amount,
                "concession_amount": concession_total,
                "net_amount": net_amount,
                "paid_amount": paid_amount,
                "outstanding_amount": outstanding,
                "currency": base_currency,
                "status": status,
                "notes": "Migrated from students.StudentEnrollmentBill",
                "created_at": now,
                "updated_at": now,
                "active": True,
            },
        )
        accounting_bill_map[enrollment_id] = accounting_bill

        for idx, line in enumerate(rows, start=1):
            fee_name = line.name or "Fee"
            target_fee_item = AccountingFeeItem.objects.filter(name=fee_name).first()
            if target_fee_item is None:
                line_code = _unique_code(fee_name, fee_codes)
                line_category = "tuition" if (line.type or "").lower() == "tuition" else "general"
                target_fee_item = AccountingFeeItem.objects.create(
                    name=fee_name,
                    code=line_code,
                    category=line_category,
                    description=line.notes,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                    active=True,
                )

            line_amount = _safe_decimal(line.amount)
            AccountingStudentBillLine.objects.get_or_create(
                student_bill=accounting_bill,
                line_sequence=idx,
                defaults={
                    "fee_item": target_fee_item,
                    "description": line.notes or fee_name,
                    "quantity": Decimal("1"),
                    "unit_amount": line_amount,
                    "line_amount": line_amount,
                    "currency": base_currency,
                    "created_at": now,
                    "updated_at": now,
                    "active": True,
                },
            )

    # 8) Concessions
    for concession in StudentConcession.objects.select_related("student", "academic_year").all():
        enrollment = Enrollment.objects.filter(
            student=concession.student,
            academic_year=concession.academic_year,
        ).first()
        linked_bill = accounting_bill_map.get(str(enrollment.id)) if enrollment else None

        AccountingConcession.objects.get_or_create(
            student=concession.student,
            academic_year=concession.academic_year,
            concession_type=concession.concession_type,
            target=concession.target,
            value=_safe_decimal(concession.value),
            defaults={
                "student_bill": linked_bill,
                "computed_amount": _safe_decimal(concession.amount),
                "currency": base_currency,
                "start_date": timezone.now().date(),
                "end_date": None,
                "is_active": bool(concession.active),
                "notes": concession.notes,
                "created_at": now,
                "updated_at": now,
                "active": True,
            },
        )

    # 9) Cash transactions
    ref_set = set(AccountingCashTransaction.objects.values_list("reference_number", flat=True))
    for tx in FinanceTransaction.objects.select_related("type", "account", "payment_method", "student").all().order_by("date", "id"):
        ref = tx.transaction_id or str(tx.id)
        if ref in ref_set:
            i = 1
            base_ref = ref
            while ref in ref_set:
                ref = f"{base_ref}-{i}"
                i += 1
        ref_set.add(ref)

        accounting_type = tx_type_map.get(str(tx.type_id))
        if accounting_type is None:
            continue

        accounting_method = payment_method_map.get(str(tx.payment_method_id))
        if accounting_method is None:
            continue

        accounting_account = bank_account_map.get(str(tx.account_id))
        if accounting_account is None:
            continue

        tx_status = "pending"
        if tx.status == "approved":
            tx_status = "approved"
        elif tx.status == "canceled":
            tx_status = "rejected"

        amount = abs(_safe_decimal(tx.amount))

        # Build payer_payee name from student fields (can't call methods in migrations)
        payer_payee = ""
        if tx.student_id:
            first_name = getattr(tx.student, "first_name", "")
            middle_name = getattr(tx.student, "middle_name", "")
            last_name = getattr(tx.student, "last_name", "")
            payer_payee = f"{first_name} {middle_name if middle_name else ''} {last_name}".strip()

        AccountingCashTransaction.objects.get_or_create(
            reference_number=ref,
            defaults={
                "bank_account": accounting_account,
                "transaction_date": tx.date,
                "transaction_type": accounting_type,
                "payment_method": accounting_method,
                "ledger_account": None,
                "amount": amount,
                "currency": base_currency,
                "exchange_rate": Decimal("1"),
                "base_amount": amount,
                "payer_payee": payer_payee,
                "description": tx.description or "Migrated transaction",
                "status": tx_status,
                "approved_by": None,
                "approved_at": None,
                "rejection_reason": "Migrated canceled transaction" if tx_status == "rejected" else None,
                "source_reference": tx.reference,
                "created_at": now,
                "updated_at": now,
                "active": True,
            },
        )


def noop_reverse(apps, schema_editor):
    # Non-destructive seed migration: no reverse delete.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0005_remove_fiscal_periods_use_academic_year"),
        ("finance", "0002_initial"),
        ("students", "0004_remove_attendance_attendance_marking_714e2a_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(forward_seed_accounting, noop_reverse),
    ]

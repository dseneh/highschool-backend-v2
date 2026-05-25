"""Student balance annotations and calculations for list/report queries."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from accounting.models import AccountingCashTransaction, AccountingStudentBill
from accounting.services.payment_allocation import get_total_paid_for_student_year
from finance.models import Transaction
from students.models import StudentEnrollmentBill


def get_effective_paid_for_student(student, academic_year) -> Decimal:
    """Sum approved tuition payments from the cash ledger for one student/year."""
    if not student or not academic_year:
        return Decimal("0")

    try:
        return get_total_paid_for_student_year(student, academic_year)
    except Exception:
        return Decimal("0")


def build_effective_paid_subquery(*, start_date, end_date) -> Subquery:
    """Subquery: approved cash received for the outer student within date range."""
    return Subquery(
        AccountingCashTransaction.objects.filter(
            Q(student=OuterRef("pk"))
            | Q(source_reference=OuterRef("id_number"))
            | Q(source_reference=OuterRef("prev_id_number")),
            status=AccountingCashTransaction.TransactionStatus.APPROVED,
            transaction_date__gte=start_date,
            transaction_date__lte=end_date,
        )
        .order_by()
        .annotate(_grp=Value(1))
        .values("_grp")
        .annotate(total=Sum("amount"))
        .values("total")[:1],
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


def annotate_student_balance_totals(
    students: QuerySet,
    *,
    academic_year=None,
    bill_year_filter: dict | None = None,
    legacy_year_filter: dict | None = None,
    legacy_student_year_filter: dict | None = None,
) -> QuerySet:
    """Attach billed_total, paid_total, and balance_total annotations."""
    from academics.models import AcademicYear

    resolved_year = academic_year
    if resolved_year is None:
        resolved_year = AcademicYear.objects.filter(current=True).only(
            "id", "start_date", "end_date"
        ).first()

    if bill_year_filter is None:
        if academic_year is not None:
            bill_year_filter = {"academic_year": academic_year}
            legacy_year_filter = {"enrollment__academic_year": academic_year}
            legacy_student_year_filter = {"academic_year": academic_year}
        else:
            bill_year_filter = {"academic_year__current": True}
            legacy_year_filter = {"enrollment__academic_year__current": True}
            legacy_student_year_filter = {"academic_year__current": True}
    else:
        legacy_year_filter = legacy_year_filter or {
            "enrollment__academic_year__current": True
        }
        legacy_student_year_filter = legacy_student_year_filter or {
            "academic_year__current": True
        }

    accounting_billed_subquery = (
        AccountingStudentBill.objects.filter(
            student=OuterRef("pk"),
            **bill_year_filter,
        )
        .order_by()
        .values("student")
        .annotate(total=Sum("net_amount"))
        .values("total")[:1]
    )
    legacy_billed_subquery = (
        StudentEnrollmentBill.objects.filter(
            enrollment__student=OuterRef("pk"),
            **legacy_year_filter,
        )
        .order_by()
        .values("enrollment__student")
        .annotate(total=Sum("amount"))
        .values("total")[:1]
    )
    legacy_paid_subquery = (
        Transaction.objects.filter(
            student=OuterRef("pk"),
            status="approved",
            type__type="income",
            **legacy_student_year_filter,
        )
        .order_by()
        .values("student")
        .annotate(total=Sum("amount"))
        .values("total")[:1]
    )

    paid_subqueries = [Subquery(legacy_paid_subquery)]
    if resolved_year is not None:
        paid_subqueries.insert(
            0,
            build_effective_paid_subquery(
                start_date=resolved_year.start_date,
                end_date=resolved_year.end_date,
            ),
        )

    return students.annotate(
        billed_total=Coalesce(
            Subquery(accounting_billed_subquery),
            Subquery(legacy_billed_subquery),
            Value(0),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        paid_total=Coalesce(
            *paid_subqueries,
            Value(0),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    ).annotate(
        balance_total=ExpressionWrapper(
            F("billed_total") - F("paid_total"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )

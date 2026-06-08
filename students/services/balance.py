"""Student balance annotations and calculations for list/report queries."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    Exists,
    ExpressionWrapper,
    F,
    OuterRef,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest

from accounting.models import AccountingCashTransaction, AccountingConcession, AccountingStudentBill
from accounting.services.payment_allocation import (
    build_student_match_q_outerref,
    get_total_paid_for_student_year,
)
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
    """Subquery: approved cash received for the outer student in a date range."""
    return Subquery(
        AccountingCashTransaction.objects.filter(
            build_student_match_q_outerref(),
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
            legacy_year_filter = legacy_year_filter or {
                "enrollment__academic_year": academic_year
            }
            legacy_student_year_filter = legacy_student_year_filter or {
                "academic_year": academic_year
            }
            concession_year_filter = {"academic_year": academic_year}
        else:
            bill_year_filter = {"academic_year__current": True}
            legacy_year_filter = legacy_year_filter or {
                "enrollment__academic_year__current": True
            }
            legacy_student_year_filter = legacy_student_year_filter or {
                "academic_year__current": True
            }
            concession_year_filter = {"academic_year__current": True}
    else:
        legacy_year_filter = legacy_year_filter or {
            "enrollment__academic_year__current": True
        }
        legacy_student_year_filter = legacy_student_year_filter or {
            "academic_year__current": True
        }
        if "academic_year" in bill_year_filter:
            concession_year_filter = {
                "academic_year": bill_year_filter["academic_year"]
            }
        else:
            concession_year_filter = {"academic_year__current": True}

    has_accounting_bills = Exists(
        AccountingStudentBill.objects.filter(
            student=OuterRef("pk"),
            **bill_year_filter,
        )
    )
    has_active_concessions = Exists(
        AccountingConcession.objects.filter(
            student=OuterRef("pk"),
            is_active=True,
            **concession_year_filter,
        )
    )

    accounting_gross_subquery = (
        AccountingStudentBill.objects.filter(
            student=OuterRef("pk"),
            **bill_year_filter,
        )
        .order_by()
        .values("student")
        .annotate(total=Sum("gross_amount"))
        .values("total")[:1]
    )
    accounting_net_subquery = (
        AccountingStudentBill.objects.filter(
            student=OuterRef("pk"),
            **bill_year_filter,
        )
        .order_by()
        .values("student")
        .annotate(total=Sum("net_amount"))
        .values("total")[:1]
    )
    concession_total_subquery = (
        AccountingConcession.objects.filter(
            student=OuterRef("pk"),
            is_active=True,
            **concession_year_filter,
        )
        .order_by()
        .values("student")
        .annotate(total=Sum("computed_amount"))
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

    accounting_paid_subquery = None
    if resolved_year is not None:
        accounting_paid_subquery = build_effective_paid_subquery(
            start_date=resolved_year.start_date,
            end_date=resolved_year.end_date,
        )

    decimal_output = DecimalField(max_digits=12, decimal_places=2)

    billed_total = Case(
        When(
            has_accounting_bills & has_active_concessions,
            then=Greatest(
                ExpressionWrapper(
                    Coalesce(
                        Subquery(accounting_gross_subquery),
                        Value(0),
                        output_field=decimal_output,
                    )
                    - Coalesce(
                        Subquery(concession_total_subquery),
                        Value(0),
                        output_field=decimal_output,
                    ),
                    output_field=decimal_output,
                ),
                Value(0),
                output_field=decimal_output,
            ),
        ),
        When(
            has_accounting_bills,
            then=Coalesce(
                Subquery(accounting_net_subquery),
                Value(0),
                output_field=decimal_output,
            ),
        ),
        default=Coalesce(
            Subquery(legacy_billed_subquery),
            Value(0),
            output_field=decimal_output,
        ),
        output_field=decimal_output,
    )

    if accounting_paid_subquery is not None:
        paid_total = Case(
            When(
                has_accounting_bills,
                then=Coalesce(
                    Subquery(accounting_paid_subquery),
                    Value(0),
                    output_field=decimal_output,
                ),
            ),
            default=Coalesce(
                Subquery(legacy_paid_subquery),
                Value(0),
                output_field=decimal_output,
            ),
            output_field=decimal_output,
        )
    else:
        paid_total = Coalesce(
            Subquery(legacy_paid_subquery),
            Value(0),
            output_field=decimal_output,
        )

    return students.annotate(
        billed_total=billed_total,
        paid_total=paid_total,
    ).annotate(
        balance_total=ExpressionWrapper(
            F("billed_total") - F("paid_total"),
            output_field=decimal_output,
        )
    )

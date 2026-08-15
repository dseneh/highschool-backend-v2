"""Central grade-visibility policy for outstanding student balances."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from rest_framework.exceptions import PermissionDenied


def get_student_year_outstanding_balance(student, academic_year) -> Decimal:
    """Return the student's current-year bill balance without touching prior ledgers."""
    from accounting.models import AccountingStudentBill

    balance = AccountingStudentBill.objects.filter(
        student=student,
        academic_year=academic_year,
    ).exclude(
        status=AccountingStudentBill.BillStatus.CANCELLED,
    ).aggregate(total=Sum("outstanding_amount"))["total"]
    return max(Decimal("0"), balance or Decimal("0"))


def enforce_grade_access(student, academic_year=None) -> None:
    """Block protected grade data when the tenant's balance gate is enabled."""
    from settings.models import GradingSettings

    settings = GradingSettings.objects.first()
    if settings is None or settings.allow_grade_view_with_outstanding_balance:
        return

    from students.services.balance import get_student_effective_outstanding_balance

    outstanding_balance = get_student_effective_outstanding_balance(student)
    if outstanding_balance <= Decimal("0"):
        return

    raise PermissionDenied(
        {
            "code": "grades_restricted_outstanding_balance",
            "detail": "Grades are currently unavailable because this student has an outstanding balance.",
            "outstanding_balance": str(outstanding_balance.quantize(Decimal("0.01"))),
            "currency": getattr(getattr(academic_year, "currency", None), "code", None),
        }
    )
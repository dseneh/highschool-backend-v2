"""Exceptional, super-admin-only academic-year grading bypass workflow."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework.exceptions import ValidationError

from common.status import EnrollmentStatus, StudentStatus, YearEndOutcome
from core.models import GradingBypassOperation, Tenant

def _json_safe(value):
    """Convert Django/Python values to primitives suitable for JSONField storage."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _get_academic_year(academic_year_id):
    from academics.models import AcademicYear

    try:
        return AcademicYear.objects.get(pk=academic_year_id)
    except (AcademicYear.DoesNotExist, ValueError, TypeError) as exc:
        raise ValidationError(
            {"academic_year": "Academic year was not found for this institution."}
        ) from exc


def _grade_counts(academic_year):
    from grading.models import Assessment, Grade, GradeBook, GradeHistory

    gradebooks = GradeBook.objects.filter(academic_year=academic_year)
    assessments = Assessment.objects.filter(gradebook__in=gradebooks)
    grades = Grade.objects.filter(academic_year=academic_year)
    return {
        "gradebooks": gradebooks.count(),
        "assessments": assessments.count(),
        "grades_results": grades.count(),
        "grade_history": GradeHistory.objects.filter(grade__in=grades).count(),
        "persisted_report_cards": 0,
        "persisted_transcripts": 0,
    }


def build_preview(
    *,
    tenant: Tenant,
    academic_year_id,
    page=1,
    page_size=25,
    search="",
    grade_level="",
    section="",
):
    """Return a tenant-scoped impact summary without making any changes."""
    with schema_context(tenant.schema_name):
        from accounting.models import AccountingStudentBill
        from academics.models import GradeLevel
        from students.models import Enrollment

        academic_year = _get_academic_year(academic_year_id)
        enrollments = Enrollment.objects.filter(academic_year=academic_year)
        open_enrollments = enrollments.filter(status=EnrollmentStatus.ENROLLED)
        if search:
            open_enrollments = open_enrollments.filter(
                Q(student__first_name__icontains=search)
                | Q(student__last_name__icontains=search)
                | Q(student__id_number__icontains=search)
            )
        if grade_level:
            open_enrollments = open_enrollments.filter(grade_level_id=grade_level)
        if section:
            open_enrollments = open_enrollments.filter(section_id=section)

        page = max(int(page or 1), 1)
        page_size = min(max(int(page_size or 25), 1), 100)
        open_enrollment_count = open_enrollments.count()
        page_enrollments = list(
            open_enrollments.select_related("student", "grade_level", "section")
            .order_by("student__last_name", "student__first_name")[
                (page - 1) * page_size:page * page_size
            ]
        )
        all_open_enrollments = enrollments.filter(status=EnrollmentStatus.ENROLLED)
        active_grade_levels = list(
            GradeLevel.objects.filter(active=True).values_list("level", flat=True)
        )
        double_promotion_eligible_students = sum(
            1
            for current_level in all_open_enrollments.values_list(
                "grade_level__level", flat=True
            )
            if sum(level > current_level for level in active_grade_levels) >= 2
        )
        overpaid = (
            AccountingStudentBill.objects.filter(academic_year=academic_year)
            .values("student_id")
            .annotate(net=Sum("net_amount"), paid=Sum("paid_amount"))
            .filter(paid__gt=F("net"))
            .count()
        )
        return _json_safe({
            "tenant": {"schema_name": tenant.schema_name, "name": tenant.name},
            "academic_year": {
                "id": str(academic_year.pk),
                "name": academic_year.name,
                "start_date": academic_year.start_date.isoformat(),
                "end_date": academic_year.end_date.isoformat(),
            },
            "affected_students": enrollments.values("student_id").distinct().count(),
            "students_requiring_year_end_completion": all_open_enrollments.count(),
            "double_promotion_eligible_students": double_promotion_eligible_students,
            "year_end_enrollments": [
                {
                    "enrollment_id": str(enrollment.pk),
                    "student_name": enrollment.student.get_full_name(),
                    "student_id_number": enrollment.student.id_number,
                    "grade_level_id": str(enrollment.grade_level_id),
                    "grade_level_order": enrollment.grade_level.level,
                    "current_grade_level": str(enrollment.grade_level),
                    "section_id": str(enrollment.section_id),
                    "section_name": str(enrollment.section),
                }
                for enrollment in page_enrollments
            ],
            "year_end_enrollment_page": {
                "page": page,
                "page_size": page_size,
                "count": open_enrollment_count,
            },
            "year_end_enrollment_filters": {
                "grade_levels": list(
                    all_open_enrollments.values("grade_level_id", "grade_level__name")
                    .distinct()
                    .order_by("grade_level__name")
                ),
                "sections": list(
                    all_open_enrollments.values("section_id", "section__name")
                    .distinct()
                    .order_by("section__name")
                ),
            },
            "next_grade_level_options": list(
                GradeLevel.objects.filter(active=True)
                .order_by("level", "name")
                .values("id", "name", "level")
            ),
            "students_with_overpayments": overpaid,
            "grading_records_to_delete": _grade_counts(academic_year),
            "financial_transactions_preserved": True,
            "financial_notice": "Payment, accounting, and finance transaction history will not be deleted or rewritten.",
        })


def _validate_outcomes(open_enrollments, outcomes, default_outcome=None):
    supplied = {
        str(key): str(value).lower().strip() for key, value in (outcomes or {}).items()
    }
    expected = {str(enrollment.pk) for enrollment in open_enrollments}
    supported = set(YearEndOutcome.all())
    normalized_default = str(default_outcome or "").lower().strip()
    if normalized_default and normalized_default not in supported:
        raise ValidationError({"default_year_end_outcome": "Unsupported year-end outcome."})
    missing = set() if normalized_default else expected - supplied.keys()
    unexpected = supplied.keys() - expected
    invalid = {key: value for key, value in supplied.items() if value not in supported}
    if missing or unexpected or invalid:
        raise ValidationError(
            {
                "detail": {
                    "missing_enrollment_ids": sorted(missing),
                    "unexpected_enrollment_ids": sorted(unexpected),
                    "unsupported_outcomes": invalid,
                }
            }
        )
    return {
        str(enrollment.pk): supplied.get(str(enrollment.pk), normalized_default)
        for enrollment in open_enrollments
    }


def _resolve_year_end_placement(enrollment, outcome, next_grade_level_id=None):
    from students.services.enrollment_lifecycle import (
        EnrollmentLifecycleError,
        resolve_year_end_placement,
    )

    try:
        return resolve_year_end_placement(
            enrollment.grade_level,
            outcome,
            next_grade_level_id,
        )
    except EnrollmentLifecycleError as exc:
        raise ValidationError({"detail": str(exc)}) from exc


def build_outcome_summary(
    *,
    tenant: Tenant,
    academic_year_id,
    year_end_outcomes,
    default_year_end_outcome=None,
    next_grade_level_overrides=None,
):
    """Preview final resolved outcomes for every open enrollment without mutation."""
    overrides = {
        str(enrollment_id): value
        for enrollment_id, value in (next_grade_level_overrides or {}).items()
        if value
    }
    with schema_context(tenant.schema_name):
        from students.models import Enrollment

        academic_year = _get_academic_year(academic_year_id)
        enrollments = list(
            Enrollment.objects.filter(
                academic_year=academic_year,
                status=EnrollmentStatus.ENROLLED,
            )
            .select_related("grade_level", "section")
            .order_by("grade_level__level", "section__name")
        )
        outcomes = _validate_outcomes(
            enrollments,
            year_end_outcomes,
            default_year_end_outcome,
        )
        status_totals = {outcome: 0 for outcome in YearEndOutcome.all()}
        class_totals = {}
        for enrollment in enrollments:
            resolved_outcome, _next_grade = _resolve_year_end_placement(
                enrollment,
                outcomes[str(enrollment.pk)],
                overrides.get(str(enrollment.pk)),
            )
            status_totals[resolved_outcome] = status_totals.get(resolved_outcome, 0) + 1
            class_key = (str(enrollment.grade_level), str(enrollment.section))
            if class_key not in class_totals:
                class_totals[class_key] = {
                    "grade_level": str(enrollment.grade_level),
                    "section": str(enrollment.section),
                    "total": 0,
                    "outcomes": {outcome: 0 for outcome in YearEndOutcome.all()},
                }
            class_totals[class_key]["total"] += 1
            class_totals[class_key]["outcomes"][resolved_outcome] += 1

        return {
            "total_students": len(enrollments),
            "status_totals": status_totals,
            "classes": list(class_totals.values()),
        }


def execute_bypass(
    *,
    tenant: Tenant,
    academic_year_id,
    actor,
    reason,
    year_end_outcomes,
    default_year_end_outcome=None,
    next_grade_level_overrides=None,
    consent_acknowledged=False,
):
    """Finalize one year, then permanently remove only its grading graph."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reason is required for a grading bypass."})
    if consent_acknowledged is not True:
        raise ValidationError({"consent_acknowledged": "Explicit consent is required before executing a grading bypass."})

    next_grade_level_overrides = {
        str(enrollment_id): value
        for enrollment_id, value in (next_grade_level_overrides or {}).items()
        if value
    }
    preview = build_preview(tenant=tenant, academic_year_id=academic_year_id)
    operation = GradingBypassOperation.objects.create(
        tenant=tenant,
        academic_year_id=str(academic_year_id),
        academic_year_name=preview["academic_year"]["name"],
        executed_by=actor,
        reason=reason,
        preview=preview,
    )
    try:
        with transaction.atomic(), schema_context(tenant.schema_name):
            from accounting.models import AccountingStudentBill
            from grading.models import GradeBook
            from students.models import Enrollment

            academic_year = _get_academic_year(academic_year_id)
            enrollments = list(
                Enrollment.objects.select_for_update()
                .select_related("student", "grade_level")
                .filter(academic_year=academic_year)
            )
            open_enrollments = [
                enrollment for enrollment in enrollments
                if enrollment.status == EnrollmentStatus.ENROLLED
            ]
            outcomes = _validate_outcomes(
                open_enrollments,
                year_end_outcomes,
                default_year_end_outcome,
            )

            settled_bill_count = AccountingStudentBill.objects.filter(
                academic_year=academic_year,
                paid_amount__gte=F("net_amount"),
                outstanding_amount__gt=Decimal("0"),
            ).update(
                outstanding_amount=Decimal("0"),
                status=AccountingStudentBill.BillStatus.PAID,
            )

            updated_count = 0
            for enrollment in open_enrollments:
                outcome, next_grade_level = _resolve_year_end_placement(
                    enrollment,
                    outcomes[str(enrollment.pk)],
                    next_grade_level_overrides.get(str(enrollment.pk)),
                )
                enrollment.status = EnrollmentStatus.COMPLETED
                enrollment.year_end_outcome = outcome
                enrollment.next_grade_level = next_grade_level
                enrollment.completion_date = date.today()
                enrollment.save(update_fields=[
                    "status", "year_end_outcome", "next_grade_level", "completion_date",
                ])
                if outcome == YearEndOutcome.GRADUATED:
                    enrollment.student.status = StudentStatus.GRADUATED
                    enrollment.student.date_of_graduation = date.today()
                    enrollment.student.save(update_fields=["status", "date_of_graduation"])
                updated_count += 1

            deleted_records = _grade_counts(academic_year)
            GradeBook.objects.filter(academic_year=academic_year).delete()

        operation.status = GradingBypassOperation.Status.COMPLETED
        operation.deleted_records = deleted_records
        operation.financial_adjustments = {
            "bills_normalized_to_zero_outstanding": settled_bill_count,
            "payment_ledger_modified": False,
        }
        operation.year_end_records_updated = updated_count
        operation.completed_at = timezone.now()
        operation.save(update_fields=[
            "status", "deleted_records", "financial_adjustments",
            "year_end_records_updated", "completed_at",
        ])
        return operation
    except Exception as exc:
        operation.status = GradingBypassOperation.Status.FAILED
        operation.failure_detail = str(exc)[:2000]
        operation.completed_at = timezone.now()
        operation.save(update_fields=["status", "failure_detail", "completed_at"])
        raise
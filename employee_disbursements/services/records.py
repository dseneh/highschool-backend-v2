"""Create and revert employee disbursement records."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from employee_disbursements.enums import DisbursementRecordStatus, DisbursementSourceType
from employee_disbursements.models import EmployeeDisbursementRecord
from employee_disbursements.services.benefit_snapshot import build_benefit_disbursement_snapshot
from employee_disbursements.services.payroll_snapshot import build_payroll_disbursement_snapshot


def _snapshots_exist_for_source(source_type: str, source_id) -> bool:
    return EmployeeDisbursementRecord.objects.filter(
        source_type=source_type,
        source_id=source_id,
        status=DisbursementRecordStatus.ACTIVE,
    ).exists()


@transaction.atomic
def create_payroll_disbursement_records(payroll_run, *, journal_entry=None, actor=None, request=None):
    """Create one active disbursement record per employee line after GL post."""
    source_id = payroll_run.id
    if _snapshots_exist_for_source(DisbursementSourceType.PAYROLL, source_id):
        return []

    paid_at = timezone.now()
    records: list[EmployeeDisbursementRecord] = []

    employee_items = (
        payroll_run.employee_items.select_related(
            "employee",
            "employee__department",
            "employee__position",
        )
        .prefetch_related("line_items")
    )

    for employee_item in employee_items:
        if EmployeeDisbursementRecord.objects.filter(
            payroll_employee_item_id=employee_item.id,
            status=DisbursementRecordStatus.ACTIVE,
        ).exists():
            continue

        snapshot = build_payroll_disbursement_snapshot(employee_item, request=request)
        run = payroll_run
        records.append(
            EmployeeDisbursementRecord(
                source_type=DisbursementSourceType.PAYROLL,
                source_id=source_id,
                payroll_employee_item=employee_item,
                employee_id=employee_item.employee_id,
                journal_entry=journal_entry,
                status=DisbursementRecordStatus.ACTIVE,
                paid_at=paid_at,
                payment_date=run.payment_date,
                period_start=run.pay_period_start,
                period_end=run.pay_period_end,
                title=run.payroll_period.name if run.payroll_period_id else run.payroll_number,
                reference_number=run.payroll_number or "",
                currency_id=run.currency_id,
                net_amount=employee_item.net_pay or 0,
                gross_amount=employee_item.gross_pay,
                snapshot=snapshot,
                created_by=actor,
                updated_by=actor,
            )
        )

    if records:
        EmployeeDisbursementRecord.objects.bulk_create(records)
    return records


@transaction.atomic
def create_benefit_disbursement_records(benefit_request, *, journal_entry=None, actor=None, request=None):
    """Create one active disbursement record per benefit request line after GL post."""
    source_id = benefit_request.id
    if _snapshots_exist_for_source(DisbursementSourceType.BENEFIT, source_id):
        return []

    paid_at = timezone.now()
    records: list[EmployeeDisbursementRecord] = []

    lines = benefit_request.lines.select_related(
        "employee",
        "employee__department",
        "employee__position",
        "request",
        "request__benefit_type",
    )

    for line in lines:
        if EmployeeDisbursementRecord.objects.filter(
            benefit_request_line_id=line.id,
            status=DisbursementRecordStatus.ACTIVE,
        ).exists():
            continue

        snapshot = build_benefit_disbursement_snapshot(line, request=request)
        records.append(
            EmployeeDisbursementRecord(
                source_type=DisbursementSourceType.BENEFIT,
                source_id=source_id,
                benefit_request_line=line,
                employee_id=line.employee_id,
                journal_entry=journal_entry,
                status=DisbursementRecordStatus.ACTIVE,
                paid_at=paid_at,
                payment_date=benefit_request.payment_date,
                period_start=benefit_request.period_start,
                period_end=benefit_request.period_end,
                title=benefit_request.benefit_type.name,
                reference_number=benefit_request.request_number,
                currency_id=benefit_request.currency_id,
                net_amount=line.final_amount or 0,
                benefit_type_name=benefit_request.benefit_type.name,
                snapshot=snapshot,
                created_by=actor,
                updated_by=actor,
            )
        )

    if records:
        EmployeeDisbursementRecord.objects.bulk_create(records)
    return records


@transaction.atomic
def revert_disbursement_records_for_source(source_type: str, source_id, *, actor=None) -> int:
    """Mark all active disbursement records for a batch as reverted."""
    now = timezone.now()
    qs = EmployeeDisbursementRecord.objects.filter(
        source_type=source_type,
        source_id=source_id,
        status=DisbursementRecordStatus.ACTIVE,
    )
    return qs.update(
        status=DisbursementRecordStatus.REVERTED,
        reverted_at=now,
        updated_by=actor,
        updated_at=now,
    )

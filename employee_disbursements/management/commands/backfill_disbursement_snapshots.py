from django.core.management.base import BaseCommand
from django.db import transaction

from employee_benefits.enums import BenefitRequestStatus
from employee_benefits.live_row_lifecycle import delete_paid_live_rows as delete_benefit_live_rows
from employee_benefits.models import BenefitRequest
from employee_benefits.paid_table_snapshot import capture_benefit_paid_table_snapshot
from employee_disbursements.enums import DisbursementRecordStatus, DisbursementSourceType
from employee_disbursements.models import EmployeeDisbursementRecord
from employee_disbursements.services.records import (
    create_benefit_disbursement_records,
    create_payroll_disbursement_records,
)
from payroll_v2.enums import PayrollStatus
from payroll_v2.live_row_lifecycle import delete_paid_live_rows as delete_payroll_live_rows
from payroll_v2.models import PayrollRunRecord
from payroll_v2.paid_table_snapshot import capture_payroll_paid_table_snapshot, snapshot_has_rebuild_payload


def _snapshot_populated(snapshot) -> bool:
    return bool(snapshot and snapshot.get("rows"))


class Command(BaseCommand):
    help = (
        "Backfill employee disbursement snapshots and paid batch table snapshots "
        "for existing paid payroll runs and benefit requests. Optionally purge live "
        "line rows once rebuild-capable snapshots exist."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts without creating records or deleting live rows.",
        )
        parser.add_argument(
            "--delete-live-rows",
            action="store_true",
            help="Delete live payroll/benefit line rows when a rebuild-capable snapshot exists.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        delete_live_rows = options["delete_live_rows"]

        paid_runs = PayrollRunRecord.objects.filter(status=PayrollStatus.PAID)
        paid_requests = BenefitRequest.objects.filter(status=BenefitRequestStatus.PAID)

        payroll_disbursement_missing = 0
        benefit_disbursement_missing = 0
        payroll_table_missing = 0
        benefit_table_missing = 0
        payroll_live_rows_deleted = 0
        benefit_live_rows_deleted = 0

        for run in paid_runs.iterator():
            needs_disbursement = not EmployeeDisbursementRecord.objects.filter(
                source_type=DisbursementSourceType.PAYROLL,
                source_id=run.id,
                status=DisbursementRecordStatus.ACTIVE,
            ).exists()
            needs_table = not _snapshot_populated(run.paid_table_snapshot) or not snapshot_has_rebuild_payload(
                run.paid_table_snapshot
            )
            has_live_rows = run.employee_items.exists()

            if needs_disbursement:
                payroll_disbursement_missing += 1
            if needs_table:
                payroll_table_missing += 1

            if dry_run:
                if delete_live_rows and has_live_rows and snapshot_has_rebuild_payload(run.paid_table_snapshot):
                    payroll_live_rows_deleted += 1
                continue

            with transaction.atomic():
                if needs_disbursement:
                    from accounting.models import AccountingPayrollPostingBatch

                    batch = AccountingPayrollPostingBatch.objects.filter(
                        idempotent_key=f"payroll-v2-run-{str(run.id)[:8]}",
                    ).select_related("journal_entry").first()
                    journal_entry = getattr(batch, "journal_entry", None) if batch else None
                    create_payroll_disbursement_records(run, journal_entry=journal_entry)
                if needs_table:
                    capture_payroll_paid_table_snapshot(run)
                    run.refresh_from_db(fields=["paid_table_snapshot"])

                if (
                    delete_live_rows
                    and has_live_rows
                    and snapshot_has_rebuild_payload(run.paid_table_snapshot)
                ):
                    delete_payroll_live_rows(run)
                    payroll_live_rows_deleted += 1

        for request in paid_requests.iterator():
            needs_disbursement = not EmployeeDisbursementRecord.objects.filter(
                source_type=DisbursementSourceType.BENEFIT,
                source_id=request.id,
                status=DisbursementRecordStatus.ACTIVE,
            ).exists()
            needs_table = not _snapshot_populated(request.paid_table_snapshot)
            has_live_rows = request.lines.exists()

            if needs_disbursement:
                benefit_disbursement_missing += 1
            if needs_table:
                benefit_table_missing += 1

            if dry_run:
                if delete_live_rows and has_live_rows and _snapshot_populated(request.paid_table_snapshot):
                    benefit_live_rows_deleted += 1
                continue

            with transaction.atomic():
                if needs_disbursement:
                    from accounting.models import AccountingJournalEntry

                    journal_entry = AccountingJournalEntry.objects.filter(
                        source="employee_benefit",
                        source_reference=str(request.id),
                        status=AccountingJournalEntry.EntryStatus.POSTED,
                    ).first()
                    create_benefit_disbursement_records(request, journal_entry=journal_entry)
                if needs_table:
                    capture_benefit_paid_table_snapshot(request)
                    request.refresh_from_db(fields=["paid_table_snapshot"])

                if delete_live_rows and has_live_rows and _snapshot_populated(request.paid_table_snapshot):
                    delete_benefit_live_rows(request)
                    benefit_live_rows_deleted += 1

        mode = "Would backfill" if dry_run else "Backfilled"
        delete_mode = "Would delete live rows for" if dry_run else "Deleted live rows for"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} disbursement records for {payroll_disbursement_missing} payroll run(s) "
                f"and {benefit_disbursement_missing} benefit request(s); "
                f"paid table snapshots for {payroll_table_missing} payroll run(s) "
                f"and {benefit_table_missing} benefit request(s)."
            )
        )
        if delete_live_rows:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{delete_mode} {payroll_live_rows_deleted} payroll run(s) "
                    f"and {benefit_live_rows_deleted} benefit request(s)."
                )
            )

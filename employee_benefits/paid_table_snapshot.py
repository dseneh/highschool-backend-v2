"""Build frozen benefit request employee table snapshot at mark-paid time."""

from __future__ import annotations

from django.utils import timezone

from common.json_utils import make_json_safe
from employee_benefits.enums import BenefitRequestStatus
from employee_benefits.models import BenefitRequest
from employee_benefits.serializers import BenefitRequestLineSerializer

BENEFIT_PAID_TABLE_COLUMNS = [
    {"key": "employee", "label": "Employee"},
    {"key": "employee_id", "label": "Employee ID"},
    {"key": "department", "label": "Department"},
    {"key": "position", "label": "Position"},
    {"key": "status", "label": "Status"},
    {"key": "computed", "label": "Computed"},
    {"key": "final", "label": "Final amount"},
    {"key": "adjusted", "label": "Adjusted"},
]


def _snapshot_populated(snapshot: dict | None) -> bool:
    return bool(snapshot and snapshot.get("rows"))


def build_benefit_paid_table_snapshot(benefit_request: BenefitRequest) -> dict:
    request = (
        BenefitRequest.objects.filter(pk=benefit_request.pk)
        .select_related("benefit_type")
        .prefetch_related(
            "lines",
            "lines__employee",
            "lines__employee__department",
            "lines__employee__position",
        )
        .first()
    )
    if request is None:
        request = benefit_request

    line_serializer = BenefitRequestLineSerializer(
        request.lines.all(),
        many=True,
    )
    rows = line_serializer.data
    for row in rows:
        row["request_status"] = BenefitRequestStatus.PAID

    return make_json_safe(
        {
            "schema_version": 1,
            "captured_at": timezone.now().isoformat(),
            "columns": BENEFIT_PAID_TABLE_COLUMNS,
            "rows": rows,
            "totals": {
                "total_amount": str(request.total_amount or 0),
                "line_count": len(rows),
            },
        }
    )


def capture_benefit_paid_table_snapshot(benefit_request: BenefitRequest) -> BenefitRequest:
    if benefit_request.status != BenefitRequestStatus.PAID:
        return benefit_request
    if _snapshot_populated(benefit_request.paid_table_snapshot):
        return benefit_request
    benefit_request.paid_table_snapshot = build_benefit_paid_table_snapshot(benefit_request)
    benefit_request.save(update_fields=["paid_table_snapshot", "updated_at"])
    return benefit_request


def clear_benefit_paid_table_snapshot(benefit_request: BenefitRequest) -> None:
    if not benefit_request.paid_table_snapshot:
        return
    benefit_request.paid_table_snapshot = {}
    benefit_request.save(update_fields=["paid_table_snapshot", "updated_at"])

"""Build benefit disbursement snapshot JSON at mark-paid time."""

from __future__ import annotations

from decimal import Decimal

from employee_benefits.models import BenefitRequestLine
from payroll_v2.school_header import build_payroll_school_header

from employee_disbursements.services.ytd import (
    active_disbursement_records_for_ytd,
    build_ytd_from_disbursement_records,
)


def _format_amount(value: Decimal | None) -> str:
    if value is None:
        return "0.00"
    return f"{value:.2f}"


def _format_date(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y")
    return str(value)


def _company_block(request=None) -> dict:
    header = build_payroll_school_header(request=request) or {}
    identity_details = []
    contact_details = []

    if header.get("id_number"):
        identity_details.append({"label": "School ID", "value": header["id_number"]})
    if header.get("workspace"):
        identity_details.append({"label": "Workspace", "value": header["workspace"]})
    if header.get("emis_number"):
        identity_details.append({"label": "EMIS No.", "value": header["emis_number"]})
    if header.get("phone"):
        contact_details.append({"label": "Phone", "value": header["phone"]})
    if header.get("email"):
        contact_details.append({"label": "Email", "value": header["email"]})
    if header.get("website"):
        contact_details.append({"label": "Website", "value": header["website"]})

    address_lines = [header["address_line"].strip()] if header.get("address_line") else []

    return {
        "name": header.get("name") or "Employer",
        "logoUrl": header.get("logo_url") or header.get("logo"),
        "slogan": header.get("slogan"),
        "identityDetails": identity_details,
        "contactDetails": contact_details,
        "addressLines": address_lines,
    }


def _build_disbursement_rows(
    *,
    employee_id,
    benefit_type_name: str,
    payment_date,
    current_line_id,
    current_period_amount: Decimal,
) -> list[dict]:
    records = active_disbursement_records_for_ytd(
        employee_id=employee_id,
        payment_date=payment_date,
        source_type="benefit",
    ).select_related("benefit_request_line", "benefit_request_line__request")

    eligible = []
    for record in records:
        snap = record.snapshot or {}
        period = snap.get("period") or {}
        if period.get("benefitName") != benefit_type_name:
            continue
        line_id = str(record.benefit_request_line_id) if record.benefit_request_line_id else None
        eligible.append(
            {
                "record_id": str(record.id),
                "line_id": line_id,
                "period_start": record.period_start,
                "period_end": record.period_end,
                "payment_date": record.payment_date,
                "amount": record.net_amount,
                "is_current": line_id == str(current_line_id),
            }
        )

    if not any(row["is_current"] for row in eligible):
        eligible.append(
            {
                "record_id": None,
                "line_id": str(current_line_id),
                "period_start": None,
                "period_end": None,
                "payment_date": payment_date,
                "amount": current_period_amount,
                "is_current": True,
            }
        )

    eligible.sort(key=lambda row: (row["payment_date"], row["period_start"] or row["payment_date"]))

    running = Decimal("0.00")
    rows: list[dict] = []
    for row in eligible:
        running += row["amount"] or Decimal("0.00")
        period_label = "—"
        if row["period_start"] and row["period_end"]:
            period_label = f"{_format_date(row['period_start'])} – {_format_date(row['period_end'])}"
        rows.append(
            {
                "label": period_label,
                "paymentDate": _format_date(row["payment_date"]),
                "periodAmount": _format_amount(row["amount"]),
                "ytd": _format_amount(running),
                "isCurrent": row["is_current"],
            }
        )
    return rows


def build_benefit_disbursement_snapshot(
    line: BenefitRequestLine,
    *,
    request=None,
) -> dict:
    benefit_request = line.request
    employee = line.employee
    benefit_type_name = benefit_request.benefit_type.name
    payment_date = benefit_request.payment_date
    period_amount = line.final_amount or Decimal("0.00")

    prior_benefit_ytd = build_ytd_from_disbursement_records(
        employee_id=employee.id,
        payment_date=payment_date,
        source_type="benefit",
    )
    benefit_type_ytd = prior_benefit_ytd.benefit_type_amounts.get(benefit_type_name, Decimal("0.00")) + period_amount
    all_benefits_ytd = prior_benefit_ytd.all_benefits + period_amount

    disbursement_rows = _build_disbursement_rows(
        employee_id=employee.id,
        benefit_type_name=benefit_type_name,
        payment_date=payment_date,
        current_line_id=line.id,
        current_period_amount=period_amount,
    )

    employee_name = employee.get_full_name().strip() or employee.id_number or "Employee"
    ytd_year = payment_date.year

    return {
        "schema_version": 1,
        "source_type": "benefit",
        "company": _company_block(request=request),
        "employee": {
            "name": employee_name,
            "idNumber": employee.id_number or "",
            "department": getattr(employee.department, "name", None),
            "position": getattr(employee.position, "title", None),
        },
        "period": {
            "benefitName": benefit_type_name,
            "periodRange": f"{_format_date(benefit_request.period_start)} – {_format_date(benefit_request.period_end)}",
            "paymentDateLabel": f"Payment date: {_format_date(payment_date)}",
            "requestNumber": benefit_request.request_number,
            "periodStart": benefit_request.period_start.isoformat(),
            "periodEnd": benefit_request.period_end.isoformat(),
            "paymentDate": payment_date.isoformat(),
        },
        "disbursementRows": disbursement_rows,
        "periodAmount": _format_amount(period_amount),
        "periodAmountRaw": str(period_amount),
        "computedAmount": _format_amount(line.computed_amount),
        "amountOverridden": bool(line.amount_overridden),
        "notes": (line.notes or "").strip() or None,
        "benefitTypeYtd": _format_amount(benefit_type_ytd),
        "allBenefitsYtd": _format_amount(all_benefits_ytd),
        "ytdColumnLabel": f"YTD {ytd_year}",
    }

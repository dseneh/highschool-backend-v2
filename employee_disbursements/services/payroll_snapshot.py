"""Build payroll disbursement snapshot JSON at mark-paid time."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from payroll_v2.enums import CalculationType, LineType
from payroll_v2.models import PayrollEmployeeItem
from payroll_v2.paystub_pdf import (
    _basic_salary_ytd_key,
    _format_time_off_cell,
    _has_time_off_activity,
    _is_basic_salary_line,
    _line_ytd_key,
    _mask_tax_id,
    _payroll_show_leave_on_paystub,
    _period_unit_label,
)
from payroll_v2.school_header import build_payroll_school_header

from employee_disbursements.services.ytd import (
    DisbursementYtdAccumulator,
    build_ytd_from_disbursement_records,
)


def _format_amount(value: Decimal | None) -> str:
    if value is None:
        return "0.00"
    return f"{value:.2f}"


def _format_ytd_amount(value: Decimal) -> str:
    return _format_amount(value if value > 0 else Decimal("0.00"))


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


def _format_employee_address(employee) -> list[str]:
    parts = [
        (employee.address or "").strip(),
        (employee.city or "").strip(),
        (employee.state or "").strip(),
        (employee.country or "").strip(),
    ]
    cleaned = [part for part in parts if part]
    return cleaned


def _frequency_label(frequency: str | None) -> str:
    if not frequency:
        return "Pay Period"
    label = frequency.replace("_", " ").title()
    return f"Pay Period - {label}"


def _ytd_total_deductions(ytd: DisbursementYtdAccumulator) -> Decimal:
    if ytd.tax > 0 and ytd.deductions >= ytd.tax:
        return ytd.deductions
    return ytd.deductions + ytd.tax


def _line_rate_units(line) -> tuple[str, str]:
    if line.calculation_type == CalculationType.PERCENTAGE:
        metadata = line.metadata or {}
        pct = metadata.get("value", metadata.get("percentage"))
        rate = f"{pct}%" if pct is not None else "-"
        return rate, "-"
    return _format_amount(line.amount or Decimal("0.00")), "1"


def _merge_ytd(
    prior: DisbursementYtdAccumulator,
    employee_item: PayrollEmployeeItem,
) -> DisbursementYtdAccumulator:
    """Combine prior active disbursement YTD with the current period amounts."""
    acc = DisbursementYtdAccumulator(
        gross=prior.gross,
        net=prior.net,
        tax=prior.tax,
        deductions=prior.deductions,
        line_amounts=dict(prior.line_amounts),
    )

    acc.gross += employee_item.gross_pay or Decimal("0.00")
    acc.net += employee_item.net_pay or Decimal("0.00")
    acc.tax += employee_item.total_tax or Decimal("0.00")
    acc.deductions += employee_item.total_deductions or Decimal("0.00")

    basic = employee_item.basic_salary or Decimal("0.00")
    earning_lines = [line for line in employee_item.line_items.all() if line.line_type == LineType.EARNING]
    has_basic_line = any(_is_basic_salary_line(line) for line in earning_lines)
    if basic > 0 and not has_basic_line:
        key = _basic_salary_ytd_key()
        acc.line_amounts[key] = acc.line_amounts.get(key, Decimal("0.00")) + basic

    for line in employee_item.line_items.all():
        key = _line_ytd_key(line.line_type, code=line.code, name=line.name)
        acc.line_amounts[key] = acc.line_amounts.get(key, Decimal("0.00")) + (line.amount or Decimal("0.00"))

    return acc


def _build_earnings(
    employee_item: PayrollEmployeeItem,
    ytd: DisbursementYtdAccumulator,
    frequency: str,
) -> list[dict]:
    rows: list[dict] = []
    earning_lines = [line for line in employee_item.line_items.all() if line.line_type == LineType.EARNING]

    def append_line(line, *, label_prefix: str = "") -> None:
        rate, units = _line_rate_units(line)
        key = _line_ytd_key(line.line_type, code=line.code, name=line.name)
        label = f"{label_prefix}{line.name}" if label_prefix else line.name
        period_amount = line.amount or Decimal("0.00")
        rows.append(
            {
                "label": label,
                "rateOrUnits": rate,
                "units": units,
                "amount": _format_amount(period_amount),
                "periodAmount": _format_amount(period_amount),
                "ytd": _format_ytd_amount(ytd.line_amounts.get(key, period_amount)),
                "ytdKey": key,
            }
        )

    if earning_lines:
        for line in earning_lines:
            append_line(line)
    elif (employee_item.basic_salary or Decimal("0.00")) > 0:
        basic = employee_item.basic_salary or Decimal("0.00")
        key = _basic_salary_ytd_key()
        rows.append(
            {
                "label": "Basic Salary",
                "rateOrUnits": _format_amount(basic),
                "units": _period_unit_label(frequency),
                "amount": _format_amount(basic),
                "periodAmount": _format_amount(basic),
                "ytd": _format_ytd_amount(ytd.line_amounts.get(key, basic)),
                "ytdKey": key,
            }
        )

    for line in employee_item.line_items.all():
        if line.line_type == LineType.BENEFIT:
            append_line(line, label_prefix="Benefit: ")
        elif line.line_type == LineType.REIMBURSEMENT:
            append_line(line, label_prefix="Reimbursement: ")

    if not rows:
        gross = employee_item.gross_pay or Decimal("0.00")
        rows.append(
            {
                "label": "Gross Earnings",
                "rateOrUnits": "-",
                "units": "-",
                "amount": _format_amount(gross),
                "periodAmount": _format_amount(gross),
                "ytd": _format_ytd_amount(ytd.gross),
                "ytdKey": "earning:gross",
            }
        )
    return rows


def _build_amount_rows(employee_item: PayrollEmployeeItem, line_type: str, ytd: DisbursementYtdAccumulator) -> list[dict]:
    rows: list[dict] = []
    for line in employee_item.line_items.all():
        if line.line_type != line_type:
            continue
        key = _line_ytd_key(line.line_type, code=line.code, name=line.name)
        label = line.name
        if line_type == LineType.TAX and line.code:
            label = f"{line.name} ({line.code})"
        period_amount = line.amount or Decimal("0.00")
        rows.append(
            {
                "label": label,
                "amount": _format_amount(period_amount),
                "periodAmount": _format_amount(period_amount),
                "ytd": _format_ytd_amount(ytd.line_amounts.get(key, period_amount)),
                "ytdKey": key,
            }
        )
    return rows


def _build_time_off_rows(employee_item: PayrollEmployeeItem) -> list[dict]:
    if not _payroll_show_leave_on_paystub():
        return []

    rows: list[dict] = []
    try:
        balances = employee_item.employee.get_leave_balance_summary(
            as_of_date=employee_item.payroll.payment_date
        )
    except Exception:
        balances = []

    for balance in balances:
        if not balance.get("include_on_paystub", True):
            continue
        leave_type = (balance.get("leave_type") or "").strip()
        if not leave_type:
            continue
        entitled = balance.get("entitled_days", 0)
        used = balance.get("used_days", 0)
        accrued = balance.get("carried_over_days", 0)
        remaining = balance.get("remaining_days", 0)
        if not _has_time_off_activity(entitled, used, accrued, remaining):
            continue
        rows.append(
            {
                "description": leave_type,
                "startingBalance": _format_time_off_cell(entitled),
                "usedInPeriod": _format_time_off_cell(used),
                "accruedInPeriod": _format_time_off_cell(accrued),
                "remainingBalance": _format_time_off_cell(remaining),
            }
        )
    return rows


def build_payroll_disbursement_snapshot(
    employee_item: PayrollEmployeeItem,
    *,
    request=None,
) -> dict:
    run = employee_item.payroll
    employee = employee_item.employee
    from payroll_v2.schedule_services import get_pay_schedule

    run_schedule = get_pay_schedule(getattr(run, "pay_schedule_id", None))
    frequency = getattr(run_schedule, "frequency", None) or ""

    prior_ytd = build_ytd_from_disbursement_records(
        employee_id=employee.id,
        payment_date=run.payment_date,
        source_type="payroll",
    )
    ytd = _merge_ytd(prior_ytd, employee_item)

    earnings = _build_earnings(employee_item, ytd, frequency)
    taxes = _build_amount_rows(employee_item, LineType.TAX, ytd)
    deductions = _build_amount_rows(employee_item, LineType.DEDUCTION, ytd)
    time_off = _build_time_off_rows(employee_item)

    employee_name = employee.get_full_name().strip() or employee.id_number or "Employee"
    tax_id_line = _mask_tax_id(getattr(employee, "tax_id", None) or getattr(employee, "national_id", None))

    period_start = run.pay_period_start
    period_end = run.pay_period_end
    period_range = (
        f"{period_start:%b} {period_start.day}, {period_start:%Y} "
        f"to {period_end:%b} {period_end.day}, {period_end:%Y}"
    )
    suffix = str(employee_item.id).replace("-", "")[:6].upper()
    stub_number = f"{run.payroll_number}-{suffix}" if run.payroll_number else suffix

    gross = employee_item.gross_pay or Decimal("0.00")
    net = employee_item.net_pay or Decimal("0.00")
    tax_total = employee_item.total_tax or Decimal("0.00")
    ded_total = employee_item.total_deductions or Decimal("0.00")
    ytd_deductions = _ytd_total_deductions(ytd)

    ytd_year = run.payment_date.year
    ytd_label = f"YTD {ytd_year}"

    return {
        "schema_version": 1,
        "source_type": "payroll",
        "company": _company_block(request=request),
        "employee": {
            "name": employee_name,
            "idNumber": employee.id_number or "",
            "taxIdLine": tax_id_line,
            "addressLines": _format_employee_address(employee),
            "department": getattr(employee.department, "name", None),
            "position": getattr(employee.position, "title", None),
        },
        "period": {
            "scheduleLabel": _frequency_label(frequency),
            "periodRange": period_range,
            "paymentDateLabel": f"Pay Date: {run.payment_date:%b} {run.payment_date.day}, {run.payment_date:%Y}",
            "stubNumber": stub_number,
            "runNumber": run.payroll_number or "",
            "periodStart": period_start.isoformat() if isinstance(period_start, date) else str(period_start),
            "periodEnd": period_end.isoformat() if isinstance(period_end, date) else str(period_end),
            "paymentDate": run.payment_date.isoformat(),
        },
        "earnings": earnings,
        "earningsTotal": {
            "amount": _format_amount(gross),
            "ytd": _format_ytd_amount(ytd.gross),
        },
        "taxes": taxes,
        "taxesTotal": {
            "amount": _format_amount(tax_total),
            "ytd": _format_ytd_amount(ytd.tax),
        },
        "deductions": deductions,
        "deductionsTotal": {
            "amount": _format_amount(ded_total),
            "ytd": _format_ytd_amount(ytd_deductions),
        },
        "timeOff": time_off,
        "netPay": _format_amount(net),
        "netPayYtd": _format_ytd_amount(ytd.net),
        "ytdColumnLabel": ytd_label,
        "periodGross": _format_amount(gross),
        "periodNet": _format_amount(net),
        "periodTax": _format_amount(tax_total),
        "periodDeductions": _format_amount(ded_total),
        "grossPay": _format_amount(gross),
    }

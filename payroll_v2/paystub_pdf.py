"""Payroll v2 employee paystub PDF generation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from common.services.pdf_components import (
    append_pdf_document_header,
    append_pdf_subtitle,
    format_pdf_amount,
    resolve_currency_symbol,
    resolve_tenant_school,
)

from .enums import CalculationType, LineType, PayrollStatus
from .models import PayrollEmployeeItem, PayrollLineItem

PAYSTUB_BORDER = colors.HexColor("#d1d5db")
PAYSTUB_HEADER_BG = colors.HexColor("#f3f4f6")
PAYSTUB_TOTAL_BG = colors.HexColor("#f9fafb")
PAYSTUB_TEXT = colors.HexColor("#111111")
PAYSTUB_TEXT_MUTED = colors.HexColor("#666666")
CONTENT_WIDTH = 7.2 * inch
TABLE_PADDING = 8
SUMMARY_WIDTH = 2.6 * inch

TAX_DEDUCTIONS_TITLE = "Tax/Deductions"
TAX_DEDUCTION_COLUMN = "Tax/Deduction"
TOTAL_TAX_DEDUCTIONS = "Total Deductions"


@dataclass
class YtdAccumulator:
    gross: Decimal = Decimal("0.00")
    net: Decimal = Decimal("0.00")
    tax: Decimal = Decimal("0.00")
    deductions: Decimal = Decimal("0.00")
    line_amounts: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: Decimal("0.00")))


@dataclass(frozen=True)
class EarningRow:
    label: str
    rate_or_units: str
    units: str
    amount: Decimal
    ytd: Decimal


@dataclass(frozen=True)
class AmountRow:
    label: str
    amount: Decimal
    ytd: Decimal


def _line_ytd_key(line_type: str, *, code: str = "", name: str = "") -> str:
    return f"{line_type}:{(code or name).strip().lower()}"


def _basic_salary_ytd_key() -> str:
    return "earning:basic_salary"


def _is_basic_salary_line(line: PayrollLineItem) -> bool:
    code = (line.code or "").strip().upper()
    name = (line.name or "").strip().lower()
    return code == "BASIC_SALARY" or name in {"basic salary", "salary"}


def _has_basic_salary_earning_line(item: PayrollEmployeeItem) -> bool:
    return any(_is_basic_salary_line(line) for line in item.line_items.all() if line.line_type == LineType.EARNING)


def _eligible_ytd_items(employee_item: PayrollEmployeeItem) -> list[PayrollEmployeeItem]:
    run = employee_item.payroll
    payment_date = run.payment_date
    year_start = date(payment_date.year, 1, 1)

    items = (
        PayrollEmployeeItem.objects.filter(
            employee_id=employee_item.employee_id,
            payroll__payment_date__gte=year_start,
            payroll__payment_date__lte=payment_date,
        )
        .select_related("payroll", "payroll__pay_schedule")
        .prefetch_related("line_items")
        .order_by("payroll__payment_date", "created_at")
    )

    eligible: list[PayrollEmployeeItem] = []
    for item in items:
        if item.id == employee_item.id:
            eligible.append(item)
        elif item.payroll.status != PayrollStatus.DRAFT:
            eligible.append(item)
    return eligible


def _accumulate_run_item(target: YtdAccumulator, item: PayrollEmployeeItem) -> None:
    target.gross += item.gross_pay or Decimal("0.00")
    target.net += item.net_pay or Decimal("0.00")
    target.tax += item.total_tax or Decimal("0.00")
    target.deductions += item.total_deductions or Decimal("0.00")

    basic = item.basic_salary or Decimal("0.00")
    if basic > 0 and not _has_basic_salary_earning_line(item):
        key = _basic_salary_ytd_key()
        target.line_amounts[key] += basic

    for line in item.line_items.all():
        key = _line_ytd_key(line.line_type, code=line.code, name=line.name)
        target.line_amounts[key] += line.amount or Decimal("0.00")


def build_ytd_accumulator(employee_item: PayrollEmployeeItem) -> YtdAccumulator:
    acc = YtdAccumulator()
    for item in _eligible_ytd_items(employee_item):
        _accumulate_run_item(acc, item)
    return acc


def _ytd_total_deductions(ytd: YtdAccumulator) -> Decimal:
    if ytd.tax > 0 and ytd.deductions >= ytd.tax:
        return ytd.deductions
    return ytd.deductions + ytd.tax


def _format_ytd(value: Decimal) -> str:
    return format_pdf_amount(value if value > 0 else Decimal("0.00"))


def _mask_tax_id(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    digits = "".join(char for char in raw if char.isdigit())
    if len(digits) >= 3:
        return f"EIN: XXXX-XX-{digits[-3:]}"
    return "EIN: XXXX-XX-XXX"


def _payroll_show_leave_on_paystub() -> bool:
    try:
        from payroll_v2.models import PayrollSettings

        settings = PayrollSettings.objects.first()
        if settings is None:
            return True
        return bool(getattr(settings, "show_leave_on_paystub", True))
    except Exception:
        return True


def _format_time_off_cell(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        parsed = Decimal(str(value))
    except Exception:
        return str(value)
    return f"{parsed:.2f}"


def _has_time_off_activity(entitled, used, accrued, remaining) -> bool:
    for value in (entitled, used, accrued, remaining):
        try:
            if Decimal(str(value or 0)) > 0:
                return True
        except Exception:
            continue
    return False


def _frequency_label(frequency: str | None) -> str:
    if not frequency:
        return "Pay Period"
    label = frequency.replace("_", " ").title()
    return f"Pay Period - {label}"


def _period_unit_label(frequency: str | None) -> str:
    mapping = {
        "weekly": "1 week",
        "biweekly": "1 period",
        "monthly": "1 month",
        "semimonthly": "1 period",
    }
    return mapping.get(frequency or "", "1 period")


def _format_employee_address(employee) -> str:
    parts = [
        (employee.address or "").strip(),
        (employee.city or "").strip(),
        (employee.state or "").strip(),
        (employee.country or "").strip(),
    ]
    cleaned = [part for part in parts if part]
    return ", ".join(cleaned) if cleaned else "—"


class PaystubV2PDF:
    """Generate a payroll v2 employee paystub matching the web export layout."""

    def __init__(self, employee_item: PayrollEmployeeItem, *, school=None):
        self.item = employee_item
        self.run = employee_item.payroll
        self.employee = employee_item.employee
        self.school = school or resolve_tenant_school()
        self.currency_symbol = resolve_currency_symbol(self.run.currency)
        self.currency_code = getattr(self.run.currency, "code", None) or self.currency_symbol
        self.frequency = getattr(self.run.pay_schedule, "frequency", None) or ""
        self.ytd = build_ytd_accumulator(employee_item)
        self.ytd_year = self.run.payment_date.year
        self._setup_styles()

    def _setup_styles(self) -> None:
        styles = getSampleStyleSheet()
        self.section_title_style = ParagraphStyle(
            "PaystubSectionTitle",
            parent=styles["Normal"],
            fontSize=11,
            fontName="Helvetica-Bold",
            textColor=PAYSTUB_TEXT,
            alignment=TA_LEFT,
            spaceBefore=6,
            spaceAfter=4,
            leading=13,
        )
        self.block_title_style = ParagraphStyle(
            "PaystubBlockTitle",
            parent=styles["Normal"],
            fontSize=11,
            fontName="Helvetica-Bold",
            textColor=PAYSTUB_TEXT,
            alignment=TA_LEFT,
            leading=13,
        )
        self.block_line_style = ParagraphStyle(
            "PaystubBlockLine",
            parent=styles["Normal"],
            fontSize=10,
            fontName="Helvetica",
            textColor=PAYSTUB_TEXT_MUTED,
            alignment=TA_LEFT,
            leading=12,
            spaceBefore=2,
        )
        self.cell_style = ParagraphStyle(
            "PaystubCell",
            parent=styles["Normal"],
            fontSize=10,
            fontName="Helvetica",
            textColor=PAYSTUB_TEXT,
            alignment=TA_LEFT,
            leading=12,
        )
        self.cell_right_style = ParagraphStyle(
            "PaystubCellRight",
            parent=self.cell_style,
            alignment=TA_RIGHT,
        )
        self.header_cell_style = ParagraphStyle(
            "PaystubHeaderCell",
            parent=styles["Normal"],
            fontSize=10,
            fontName="Helvetica-Bold",
            textColor=PAYSTUB_TEXT,
            alignment=TA_LEFT,
            leading=12,
        )
        self.header_cell_right_style = ParagraphStyle(
            "PaystubHeaderCellRight",
            parent=self.header_cell_style,
            alignment=TA_RIGHT,
        )
        self.total_cell_style = ParagraphStyle(
            "PaystubTotalCell",
            parent=self.cell_style,
            fontName="Helvetica-Bold",
        )
        self.total_cell_right_style = ParagraphStyle(
            "PaystubTotalCellRight",
            parent=self.cell_right_style,
            fontName="Helvetica-Bold",
        )
        self.summary_label_style = ParagraphStyle(
            "PaystubSummaryLabel",
            parent=self.cell_style,
            fontName="Helvetica-Bold",
        )
        self.summary_value_style = ParagraphStyle(
            "PaystubSummaryValue",
            parent=self.cell_right_style,
            fontName="Helvetica-Bold",
        )

    def _money(self, value) -> str:
        return format_pdf_amount(value)

    def _employee_name(self) -> str:
        name = self.employee.get_full_name().strip()
        if name:
            return name
        return self.employee.id_number or "Employee"

    def _employee_title(self) -> str:
        name = self._employee_name()
        if self.employee.id_number:
            return f"{name} (ID #: {self.employee.id_number})"
        return name

    def _stub_number(self) -> str:
        suffix = str(self.item.id).replace("-", "")[:6].upper()
        if self.run.payroll_number:
            return f"Stub Number: {self.run.payroll_number}-{suffix}"
        return f"Stub Number: {suffix}"

    def _line_rate_units(self, line: PayrollLineItem) -> tuple[str, str]:
        if line.calculation_type == CalculationType.PERCENTAGE:
            metadata = line.metadata or {}
            pct = metadata.get("value", metadata.get("percentage"))
            rate = f"{pct}%" if pct is not None else "—"
            return rate, "—"
        return self._money(line.amount), "1"

    def _currency_note(self) -> str:
        if self.currency_code and self.currency_symbol and self.currency_code != self.currency_symbol:
            return f"All amounts in {self.currency_code} ({self.currency_symbol})"
        return f"All amounts in {self.currency_code or self.currency_symbol}"

    def _build_document_header(self, story: list) -> None:
        append_pdf_document_header(
            story,
            self.school,
            "EMPLOYEE PAYSTUB",
            show_statement_date=False,
            bottom_spacer_inches=0.04,
            header_width_inches=7.2,
        )
        append_pdf_subtitle(story, self._currency_note())

    def _table_padding_style(self) -> list:
        return [
            ("LEFTPADDING", (0, 0), (-1, -1), TABLE_PADDING),
            ("RIGHTPADDING", (0, 0), (-1, -1), TABLE_PADDING),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]

    def _paystub_table_style(self, *, header_rows: tuple[int, ...] = (0,), total_row: int | None = None) -> list:
        styles = [
            ("BOX", (0, 0), (-1, -1), 0.6, PAYSTUB_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, PAYSTUB_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            *self._table_padding_style(),
        ]
        for row_index in header_rows:
            styles.extend(
                [
                    ("BACKGROUND", (0, row_index), (-1, row_index), PAYSTUB_HEADER_BG),
                    ("FONTNAME", (0, row_index), (-1, row_index), "Helvetica-Bold"),
                ]
            )
        if total_row is not None:
            styles.extend(
                [
                    ("BACKGROUND", (0, total_row), (-1, total_row), PAYSTUB_TOTAL_BG),
                    ("FONTNAME", (0, total_row), (-1, total_row), "Helvetica-Bold"),
                ]
            )
        return styles

    def _build_employee_period_grid(self) -> Table:
        department = getattr(self.employee.department, "name", None) or "—"
        position = getattr(self.employee.position, "title", None) or "—"
        address = _format_employee_address(self.employee)
        period_range = (
            f"{self.run.pay_period_start:%b} {self.run.pay_period_start.day}, {self.run.pay_period_start:%Y} "
            f"to {self.run.pay_period_end:%b} {self.run.pay_period_end.day}, {self.run.pay_period_end:%Y}"
        )
        pay_date = f"Pay Date: {self.run.payment_date:%b} {self.run.payment_date.day}, {self.run.payment_date:%Y}"
        tax_line = _mask_tax_id(getattr(self.employee, "tax_id", None) or getattr(self.employee, "national_id", None))

        left_lines = [Paragraph(self._employee_title(), self.block_title_style)]
        if tax_line:
            left_lines.append(Paragraph(tax_line, self.block_line_style))
        left_lines.extend(
            [
                Paragraph(address, self.block_line_style),
                Paragraph(f"Department: {department}", self.block_line_style),
                Paragraph(f"Position: {position}", self.block_line_style),
            ]
        )
        right_lines = [
            Paragraph(_frequency_label(self.frequency), self.block_title_style),
            Paragraph(period_range, self.block_line_style),
            Paragraph(pay_date, self.block_line_style),
            Paragraph(self._stub_number(), self.block_line_style),
        ]

        table = Table(
            [[left_lines, right_lines]],
            colWidths=[CONTENT_WIDTH / 2, CONTENT_WIDTH / 2],
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, PAYSTUB_BORDER),
                    ("LINEAFTER", (0, 0), (0, -1), 0.6, PAYSTUB_BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    *self._table_padding_style(),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        return table

    def _build_section_table(
        self,
        title: str,
        headers: list[str],
        rows: Iterable[list],
        *,
        footer: list | None = None,
        empty_label: str = "None",
        col_widths: list[float],
    ) -> list:
        flowables: list = [Paragraph(title, self.section_title_style)]
        table_data = [[Paragraph(header, self.header_cell_right_style if index else self.header_cell_style) for index, header in enumerate(headers)]]
        row_items = list(rows)

        if row_items:
            for row in row_items:
                table_data.append(
                    [
                        Paragraph(str(row[0]), self.cell_style),
                        *[Paragraph(str(cell), self.cell_right_style) for cell in row[1:]],
                    ]
                )
        else:
            table_data.append(
                [
                    Paragraph(empty_label, ParagraphStyle("Empty", parent=self.cell_style, textColor=PAYSTUB_TEXT_MUTED)),
                    *[Paragraph("", self.cell_style) for _ in headers[1:]],
                ]
            )

        total_row = None
        if footer:
            total_row = len(table_data)
            table_data.append(
                [
                    Paragraph(str(footer[0]), self.total_cell_style),
                    *[Paragraph(str(cell), self.total_cell_right_style) for cell in footer[1:]],
                ]
            )

        table = Table(table_data, colWidths=col_widths, hAlign="LEFT")
        table.setStyle(TableStyle(self._paystub_table_style(header_rows=(0,), total_row=total_row)))
        flowables.append(table)
        return flowables

    def _earning_rows(self) -> list[EarningRow]:
        rows: list[EarningRow] = []
        earning_lines = [line for line in self.item.line_items.all() if line.line_type == LineType.EARNING]

        def append_line(line: PayrollLineItem, *, label_prefix: str = "") -> None:
            rate, units = self._line_rate_units(line)
            key = _line_ytd_key(line.line_type, code=line.code, name=line.name)
            label = f"{label_prefix}{line.name}" if label_prefix else line.name
            rows.append(
                EarningRow(
                    label=label,
                    rate_or_units=rate,
                    units=units,
                    amount=line.amount,
                    ytd=self.ytd.line_amounts.get(key, line.amount),
                )
            )

        if earning_lines:
            for line in earning_lines:
                append_line(line)
        elif (self.item.basic_salary or Decimal("0.00")) > 0:
            basic = self.item.basic_salary
            key = _basic_salary_ytd_key()
            rows.append(
                EarningRow(
                    label="Basic Salary",
                    rate_or_units=self._money(basic),
                    units=_period_unit_label(self.frequency),
                    amount=basic,
                    ytd=self.ytd.line_amounts.get(key, basic),
                )
            )

        for line in self.item.line_items.all():
            if line.line_type == LineType.BENEFIT:
                append_line(line, label_prefix="Benefit: ")
            elif line.line_type == LineType.REIMBURSEMENT:
                append_line(line, label_prefix="Reimbursement: ")

        if not rows:
            rows.append(
                EarningRow(
                    label="Gross Earnings",
                    rate_or_units="—",
                    units="—",
                    amount=self.item.gross_pay,
                    ytd=self.ytd.gross,
                )
            )
        return rows

    def _amount_rows(self, line_type: str) -> list[AmountRow]:
        rows: list[AmountRow] = []
        for line in self.item.line_items.all():
            if line.line_type != line_type:
                continue
            key = _line_ytd_key(line.line_type, code=line.code, name=line.name)
            label = line.name
            if line_type == LineType.TAX and line.code:
                label = f"{line.name} ({line.code})"
            rows.append(
                AmountRow(
                    label=label,
                    amount=line.amount,
                    ytd=self.ytd.line_amounts.get(key, line.amount),
                )
            )
        return rows

    def _five_col_widths(self) -> list[float]:
        # Must sum to CONTENT_WIDTH so every section table aligns edge-to-edge.
        return [2.2 * inch, 1.2 * inch, 0.8 * inch, 1.5 * inch, 1.5 * inch]

    def _build_earnings_section(self) -> list:
        earning_rows = self._earning_rows()
        rows = [[row.label, row.rate_or_units, row.units, self._money(row.amount), _format_ytd(row.ytd)] for row in earning_rows]
        footer = None
        if earning_rows:
            footer = [
                "Total Gross Amount",
                "",
                "",
                self._money(self.item.gross_pay),
                _format_ytd(self.ytd.gross),
            ]
        return self._build_section_table(
            "Earnings",
            ["Earnings", "Rate/Units", "Units", "Amount", "YTD"],
            rows,
            footer=footer,
            empty_label="No earnings for this period",
            col_widths=self._five_col_widths(),
        )

    def _build_tax_deductions_section(self) -> list:
        tax_rows = self._amount_rows(LineType.TAX)
        deduction_rows = self._amount_rows(LineType.DEDUCTION)
        combined_rows = tax_rows + deduction_rows
        rows = [[row.label, "", "", self._money(row.amount), _format_ytd(row.ytd)] for row in combined_rows]
        total_deductions = self.item.total_deductions
        total_ytd = _ytd_total_deductions(self.ytd)
        footer = None
        if combined_rows or total_deductions:
            footer = [TOTAL_TAX_DEDUCTIONS, "", "", self._money(total_deductions), _format_ytd(total_ytd)]
        return self._build_section_table(
            TAX_DEDUCTIONS_TITLE,
            [TAX_DEDUCTION_COLUMN, "", "", "Amount", "YTD"],
            rows,
            footer=footer,
            empty_label="No tax or deductions for this period",
            col_widths=self._five_col_widths(),
        )

    def _time_off_rows(self) -> list[list[str]]:
        if not _payroll_show_leave_on_paystub():
            return []

        rows: list[list[str]] = []
        try:
            balances = self.employee.get_leave_balance_summary(as_of_date=self.run.payment_date)
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
                [
                    leave_type,
                    _format_time_off_cell(entitled),
                    _format_time_off_cell(used),
                    _format_time_off_cell(accrued),
                    _format_time_off_cell(remaining),
                ]
            )
        return rows

    def _build_time_off_section(self) -> list:
        rows = self._time_off_rows()
        if not rows:
            return []
        footer = None
        if rows:
            footer = ["Remaining Balance", "", "", "", rows[-1][4]]
        return self._build_section_table(
            "Time-Off",
            [
                "Description",
                "Starting Balance (days)",
                "Used in Period (days)",
                "Accrued in Period (days)",
                "Remaining Balance (days)",
            ],
            rows,
            footer=footer,
            empty_label="No time-off records for this period",
            col_widths=self._five_col_widths(),
        )

    def _build_net_pay_summary(self) -> Table:
        summary = Table(
            [
                [Paragraph("Net Pay", self.summary_label_style), Paragraph(self._money(self.item.net_pay), self.summary_value_style)],
                [
                    Paragraph("Year-To-Date (Net Pay)", self.summary_label_style),
                    Paragraph(_format_ytd(self.ytd.net), self.summary_value_style),
                ],
            ],
            colWidths=[1.5 * inch, 1.1 * inch],
            hAlign="LEFT",
        )
        summary.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, PAYSTUB_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, PAYSTUB_BORDER),
                    *self._table_padding_style(),
                ]
            )
        )
        wrapper = Table([[None, summary]], colWidths=[CONTENT_WIDTH - SUMMARY_WIDTH, SUMMARY_WIDTH], hAlign="LEFT")
        wrapper.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return wrapper

    def _build_body(self) -> list:
        flowables: list = []
        flowables.append(self._build_employee_period_grid())
        flowables.append(Spacer(1, 0.08 * inch))
        flowables.extend(self._build_earnings_section())
        flowables.extend(self._build_tax_deductions_section())
        flowables.extend(self._build_time_off_section())
        flowables.append(Spacer(1, 0.08 * inch))
        flowables.append(self._build_net_pay_summary())
        return flowables

    def generate(self) -> bytes:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=0.4 * inch,
            bottomMargin=0.4 * inch,
            leftMargin=0.4 * inch,
            rightMargin=0.4 * inch,
        )
        story: list = []
        self._build_document_header(story)
        story.extend(self._build_body())
        doc.build(story)
        return buffer.getvalue()


def build_paystub_v2_pdf_bytes(employee_item: PayrollEmployeeItem, *, school=None) -> bytes:
    return PaystubV2PDF(employee_item, school=school).generate()

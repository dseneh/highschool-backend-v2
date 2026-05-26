"""Branded employee payslip PDF generation."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from typing import Iterable

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from common.services.pdf_components import (
    PDF_BORDER_ACCENT,
    PDF_CHART_DEDUCTIONS,
    PDF_CHART_GROSS,
    PDF_CHART_NET,
    PDF_CHART_TAX,
    PDF_NET_HIGHLIGHT,
    PDF_PRIMARY,
    PDF_TEXT,
    PDF_TEXT_MUTED,
    append_pdf_document_header,
    append_pdf_subtitle,
    format_pdf_currency,
    pdf_alternating_row_style,
    pdf_base_table_style,
    pdf_primary_header_row_style,
    resolve_currency_symbol,
    resolve_tenant_school,
)


class PayslipPDF:
    """Generate a school-branded employee payslip."""

    def __init__(self, payslip, *, school=None):
        self.payslip = payslip
        self.school = school or resolve_tenant_school()
        self.employee = payslip.employee
        self.run = payslip.payroll_run
        self.period = self.run.period
        self.schedule = self.period.schedule
        self.currency_symbol = resolve_currency_symbol(payslip.currency)
        self._setup_styles()

    def _setup_styles(self) -> None:
        styles = getSampleStyleSheet()
        self.section_style = ParagraphStyle(
            "PayslipSection",
            parent=styles["Heading2"],
            fontSize=9,
            fontName="Helvetica-Bold",
            textColor=PDF_PRIMARY,
            alignment=TA_LEFT,
            spaceBefore=8,
            spaceAfter=4,
        )
        self.label_style = ParagraphStyle(
            "PayslipLabel",
            parent=styles["Normal"],
            fontSize=7,
            fontName="Helvetica-Bold",
            textColor=PDF_TEXT_MUTED,
            alignment=TA_LEFT,
            leading=9,
        )
        self.header_label_style = ParagraphStyle(
            "PayslipHeaderLabel",
            parent=self.label_style,
            textColor=colors.white,
        )
        self.value_style = ParagraphStyle(
            "PayslipValue",
            parent=styles["Normal"],
            fontSize=9,
            fontName="Helvetica",
            textColor=PDF_TEXT,
            alignment=TA_LEFT,
            leading=11,
        )
        self.summary_value_style = ParagraphStyle(
            "PayslipSummaryValue",
            parent=self.value_style,
            fontName="Helvetica-Bold",
            fontSize=10,
            alignment=TA_CENTER,
        )
        self.footer_style = ParagraphStyle(
            "PayslipFooter",
            parent=styles["Normal"],
            fontSize=7,
            fontName="Helvetica",
            textColor=PDF_TEXT_MUTED,
            alignment=TA_CENTER,
            leading=10,
        )

    def _money(self, value) -> str:
        return format_pdf_currency(value, self.currency_symbol)

    def _employee_name(self) -> str:
        name = self.employee.get_full_name().strip()
        if name:
            return name
        return self.employee.id_number or "Employee"

    def _build_header(self, story: list) -> None:
        statement_date = timezone.localtime(self.payslip.generated_at).strftime("%B %d, %Y")
        append_pdf_document_header(
            story,
            self.school,
            "EMPLOYEE PAYSLIP",
            show_statement_date=True,
            statement_date_text=f"Generated: {statement_date}",
            bottom_spacer_inches=0.04,
            header_width_inches=7.2,
        )
        period_text = (
            f"Pay Period: {self.period.name} "
            f"({self.period.start_date:%b %d, %Y} – {self.period.end_date:%b %d, %Y}) · "
            f"Payment Date: {self.period.payment_date:%b %d, %Y}"
        )
        append_pdf_subtitle(story, period_text)

    def _build_employee_info(self, story: list) -> None:
        department = getattr(self.employee.department, "name", None) or "—"
        position = getattr(self.employee.position, "title", None) or "—"
        paid_on = (
            timezone.localtime(self.run.paid_at).strftime("%B %d, %Y")
            if self.run.paid_at
            else "—"
        )

        data = [
            [
                Paragraph("EMPLOYEE", self.header_label_style),
                Paragraph("EMPLOYEE ID", self.header_label_style),
                Paragraph("DEPARTMENT", self.header_label_style),
                Paragraph("POSITION", self.header_label_style),
            ],
            [
                Paragraph(self._employee_name(), self.value_style),
                Paragraph(self.employee.id_number or "—", self.value_style),
                Paragraph(department, self.value_style),
                Paragraph(position, self.value_style),
            ],
            [
                Paragraph("PAY SCHEDULE", self.header_label_style),
                Paragraph("PAYROLL RUN", self.header_label_style),
                Paragraph("STATUS", self.header_label_style),
                Paragraph("PAID ON", self.header_label_style),
            ],
            [
                Paragraph(self.schedule.name, self.value_style),
                Paragraph(self.period.name, self.value_style),
                Paragraph(self.run.get_status_display(), self.value_style),
                Paragraph(paid_on, self.value_style),
            ],
        ]

        table = Table(data, colWidths=[1.8 * inch, 1.5 * inch, 1.7 * inch, 1.7 * inch])
        table.setStyle(
            TableStyle(
                [
                    *pdf_base_table_style(),
                    *pdf_primary_header_row_style(0),
                    *pdf_primary_header_row_style(2),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 0.08 * inch))

    def _build_amount_table(
        self,
        story: list,
        title: str,
        rows: Iterable[tuple[str, object]],
        *,
        emphasize_last: bool = False,
    ) -> None:
        story.append(Paragraph(title, self.section_style))
        table_data = [
            [
                Paragraph("Description", self.header_label_style),
                Paragraph(
                    "Amount",
                    ParagraphStyle(
                        "AmtHdr",
                        parent=self.header_label_style,
                        alignment=TA_RIGHT,
                    ),
                ),
            ]
        ]
        row_items = list(rows)
        for label, amount in row_items:
            table_data.append(
                [
                    Paragraph(label, self.value_style),
                    Paragraph(
                        self._money(amount),
                        ParagraphStyle("AmtVal", parent=self.value_style, alignment=TA_RIGHT),
                    ),
                ]
            )

        if not row_items:
            table_data.append(
                [
                    Paragraph("No entries", self.value_style),
                    Paragraph(
                        self._money(0),
                        ParagraphStyle("AmtVal", parent=self.value_style, alignment=TA_RIGHT),
                    ),
                ]
            )

        styles = [
            *pdf_base_table_style(),
            *pdf_primary_header_row_style(0),
            *pdf_alternating_row_style(1),
        ]
        if emphasize_last and len(table_data) > 1:
            last = len(table_data) - 1
            styles.extend(
                [
                    ("BACKGROUND", (0, last), (-1, last), PDF_NET_HIGHLIGHT),
                    ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
                ]
            )
        table = Table(table_data, colWidths=[4.8 * inch, 1.9 * inch])
        table.setStyle(TableStyle(styles))
        story.append(table)
        story.append(Spacer(1, 0.06 * inch))

    def _breakdown_rows(self, items: list[dict]) -> list[tuple[str, object]]:
        rows: list[tuple[str, object]] = []
        for item in items or []:
            name = str(item.get("name") or item.get("rule") or "Item")
            code = item.get("code")
            label = f"{name} ({code})" if code else name
            rows.append((label, item.get("amount", 0)))
        return rows

    def _build_earnings(self, story: list) -> None:
        payslip = self.payslip
        rows: list[tuple[str, object]] = [
            ("Basic Salary", payslip.basic_salary),
        ]
        if Decimal(str(payslip.overtime_hours or 0)) > 0 or Decimal(str(payslip.overtime_pay or 0)) > 0:
            rows.append(
                (
                    f"Overtime ({payslip.overtime_hours} hrs)",
                    payslip.overtime_pay,
                )
            )
        rows.extend(self._breakdown_rows((payslip.breakdown or {}).get("allowances", [])))
        rows.append(("Gross Pay", payslip.gross_pay))
        self._build_amount_table(story, "EARNINGS", rows, emphasize_last=True)

    def _build_adjustments(self, story: list) -> None:
        payslip = self.payslip
        adjustment_rows = self._breakdown_rows((payslip.breakdown or {}).get("adjustments", []))
        if not adjustment_rows and Decimal(str(payslip.adjustments or 0)) <= 0:
            return
        if not adjustment_rows and Decimal(str(payslip.adjustments or 0)) > 0:
            adjustment_rows = [("Adjustments", payslip.adjustments)]
        self._build_amount_table(story, "POST-NET ADJUSTMENTS", adjustment_rows)

    def _build_deductions(self, story: list) -> None:
        payslip = self.payslip
        breakdown = payslip.breakdown or {}
        rows = self._breakdown_rows(breakdown.get("deductions", []))
        rows.extend(self._breakdown_rows(breakdown.get("tax", [])))
        if Decimal(str(payslip.tax or 0)) > 0 and not breakdown.get("tax"):
            rows.append(("Tax", payslip.tax))
        if Decimal(str(payslip.deductions or 0)) > 0 and not breakdown.get("deductions"):
            rows.append(("Total Deductions", payslip.deductions))
        has_adjustments = Decimal(str(payslip.adjustments or 0)) > 0
        if has_adjustments:
            taxable_net = (
                Decimal(str(payslip.gross_pay or 0))
                - Decimal(str(payslip.tax or 0))
                - Decimal(str(payslip.deductions or 0))
            )
            rows.append(("Net Pay (before adjustments)", taxable_net))
        else:
            rows.append(("Net Pay", payslip.net_pay))
        self._build_amount_table(story, "DEDUCTIONS & NET PAY", rows, emphasize_last=True)

    def _build_summary_strip(self, story: list) -> None:
        payslip = self.payslip
        summary_columns = [
            ("Gross Pay", payslip.gross_pay, PDF_CHART_GROSS),
            ("Tax", payslip.tax, PDF_CHART_TAX),
            ("Deductions", payslip.deductions, PDF_CHART_DEDUCTIONS),
            ("Net Pay", payslip.net_pay, PDF_CHART_NET),
        ]

        summary_data = [
            [
                Paragraph(label, self.header_label_style)
                for label, _, _ in summary_columns
            ],
            [
                Paragraph(self._money(amount), self.summary_value_style)
                for _, amount, _ in summary_columns
            ],
        ]

        table = Table(summary_data, colWidths=[1.675 * inch] * 4)
        styles = [
            *pdf_base_table_style(),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("BACKGROUND", (3, 1), (3, 1), PDF_NET_HIGHLIGHT),
        ]
        for column_index, (_, _, color) in enumerate(summary_columns):
            styles.extend(
                [
                    ("BACKGROUND", (column_index, 0), (column_index, 0), color),
                    ("TEXTCOLOR", (column_index, 0), (column_index, 0), colors.white),
                    ("FONTNAME", (column_index, 0), (column_index, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (column_index, 0), (column_index, 0), 8),
                ]
            )
        table.setStyle(TableStyle(styles))
        story.append(table)
        story.append(Spacer(1, 0.1 * inch))

    def _build_footer(self, story: list) -> None:
        story.append(
            HRFlowable(
                width="100%",
                thickness=0.5,
                lineCap="round",
                color=PDF_BORDER_ACCENT,
                spaceBefore=0.04 * inch,
                spaceAfter=0.06 * inch,
            )
        )
        story.append(
            Paragraph(
                "This payslip is computer-generated and does not require a signature. "
                "Please retain for your records.",
                self.footer_style,
            )
        )

    def generate(self) -> bytes:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=0.35 * inch,
            bottomMargin=0.35 * inch,
            leftMargin=0.4 * inch,
            rightMargin=0.4 * inch,
        )
        story: list = []
        self._build_header(story)
        self._build_employee_info(story)
        self._build_summary_strip(story)
        self._build_earnings(story)
        self._build_deductions(story)
        self._build_adjustments(story)
        if Decimal(str(self.payslip.adjustments or 0)) > 0:
            self._build_amount_table(
                story,
                "TAKE HOME PAY",
                [("Take Home Pay", self.payslip.net_pay)],
                emphasize_last=True,
            )
        self._build_footer(story)
        doc.build(story)
        return buffer.getvalue()


def build_payslip_pdf_bytes(payslip, *, school=None) -> bytes:
    return PayslipPDF(payslip, school=school).generate()

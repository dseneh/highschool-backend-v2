"""Cash transaction PDF export helpers."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from accounting.models import AccountingCashTransaction, AccountingCurrency
from common.services.pdf_components import append_pdf_document_header, resolve_tenant_school


def _value(value: str | None) -> str:
    text = (value or "").strip()
    return text or "-"


def _format_money(value: Decimal | int | float | None, code: str | None) -> str:
    numeric = Decimal(str(value or 0))
    return f"{(code or 'USD').upper()} {numeric:,.2f}"


def _name_from_actor(actor) -> str:
    if not actor:
        return "System"
    get_full_name = getattr(actor, "get_full_name", None)
    if callable(get_full_name):
        full_name = (get_full_name() or "").strip()
        if full_name:
            return full_name
    for attr in ("full_name", "username", "email"):
        value = getattr(actor, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(actor)


def _build_activity_timeline(transaction: AccountingCashTransaction) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []

    if transaction.created_at:
        items.append(
            {
                "date": transaction.created_at.strftime("%Y-%m-%d %H:%M"),
                "event": "Created",
                "details": "Cash transaction record was created.",
                "actor": _name_from_actor(getattr(transaction, "created_by", None)),
            }
        )

    if transaction.approved_at:
        items.append(
            {
                "date": transaction.approved_at.strftime("%Y-%m-%d %H:%M"),
                "event": "Approved",
                "details": "Transaction was approved and prepared for posting.",
                "actor": _value(transaction.approved_by),
            }
        )

    if transaction.completed_at:
        items.append(
            {
                "date": transaction.completed_at.strftime("%Y-%m-%d %H:%M"),
                "event": "Completed",
                "details": "Posting workflow completed successfully.",
                "actor": _value(transaction.completed_by),
            }
        )

    if transaction.rejected_at:
        items.append(
            {
                "date": transaction.rejected_at.strftime("%Y-%m-%d %H:%M"),
                "event": "Rejected",
                "details": _value(transaction.rejection_reason) if transaction.rejection_reason else "Transaction was rejected.",
                "actor": _value(transaction.rejected_by),
            }
        )

    if transaction.updated_at and transaction.created_at and transaction.updated_at > transaction.created_at:
        items.append(
            {
                "date": transaction.updated_at.strftime("%Y-%m-%d %H:%M"),
                "event": "Updated",
                "details": "Transaction details were modified.",
                "actor": _name_from_actor(getattr(transaction, "updated_by", None)),
            }
        )

    items.sort(key=lambda item: item["date"], reverse=True)
    return items


class CashTransactionPDF:
    """Generate a report-style PDF for one cash transaction."""

    def __init__(self, transaction: AccountingCashTransaction, school=None):
        self.transaction = transaction
        self.school = school
        self.base_currency_code = self._resolve_base_currency_code()
        self.styles = getSampleStyleSheet()
        self._setup_styles()

    def _resolve_base_currency_code(self) -> str:
        base_currency = (
            AccountingCurrency.objects.filter(is_active=True, is_base_currency=True)
            .only("code")
            .first()
        )
        if base_currency and base_currency.code:
            return str(base_currency.code).upper()
        tx_currency_code = getattr(self.transaction.currency, "code", None)
        return str(tx_currency_code or "USD").upper()

    def _setup_styles(self) -> None:
        self.section_title_style = ParagraphStyle(
            "CashSectionTitle",
            parent=self.styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=colors.HexColor("#1e3a8a"),
            alignment=TA_LEFT,
            spaceAfter=3,
            spaceBefore=2,
        )
        self.cell_label_style = ParagraphStyle(
            "CashCellLabel",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.HexColor("#334155"),
            leading=10,
        )
        self.cell_value_style = ParagraphStyle(
            "CashCellValue",
            parent=self.styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=colors.HexColor("#0f172a"),
            leading=10,
        )
        self.timeline_header_style = ParagraphStyle(
            "CashTimelineHeader",
            parent=self.styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.white,
            leading=10,
        )

    def _build_header(self, story: list) -> None:
        append_pdf_document_header(
            story,
            self.school,
            "CASH TRANSACTION REPORT",
            show_statement_date=False,
            bottom_spacer_inches=0.04,
        )

        reference = _value(self.transaction.reference_number)
        status_value = _value(self.transaction.status).upper()
        summary_table = Table(
            [[
                Paragraph(f"<b>Reference:</b> {reference}", self.cell_value_style),
                Paragraph(f"<b>Status:</b> {status_value}", self.cell_value_style),
            ]],
            colWidths=[3.9 * inch, 3.3 * inch],
        )
        summary_table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#1e3a8a")),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef2ff")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(summary_table)
        story.append(Spacer(1, 0.08 * inch))

    def _build_details_section(self, story: list) -> None:
        story.append(Paragraph("TRANSACTION DETAILS", self.section_title_style))

        tx = self.transaction
        transaction_currency_code = tx.currency.code if tx.currency else None
        rows = [
            ("Transaction Date", tx.transaction_date.isoformat() if tx.transaction_date else "-"),
            ("Transaction Type", _value(tx.transaction_type.name if tx.transaction_type else None)),
            ("Amount", _format_money(tx.amount, transaction_currency_code)),
            ("Base Amount", _format_money(tx.base_amount, self.base_currency_code)),
            ("Exchange Rate", f"{Decimal(str(tx.exchange_rate or 1)):.6f}"),
            ("Bank Account", _value(tx.bank_account.account_name if tx.bank_account else None)),
            ("Payment Method", _value(tx.payment_method.name if tx.payment_method else None)),
            ("Payer / Payee", _value(tx.payer_payee)),
            ("Source Reference", _value(tx.source_reference)),
            ("Journal Entry", _value(tx.journal_entry.reference_number if tx.journal_entry else None)),
            ("Description", _value(tx.description)),
            ("Notes", _value(tx.notes)),
            ("Created At", tx.created_at.strftime("%Y-%m-%d %H:%M") if tx.created_at else "-"),
            ("Last Updated", tx.updated_at.strftime("%Y-%m-%d %H:%M") if tx.updated_at else "-"),
        ]

        table_data = [
            [
                Paragraph(label, self.cell_label_style),
                Paragraph(value, self.cell_value_style),
            ]
            for label, value in rows
        ]

        details_table = Table(table_data, colWidths=[2.2 * inch, 5.0 * inch])
        details_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                    ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#64748b")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(details_table)
        story.append(Spacer(1, 0.1 * inch))

    def _build_timeline_section(self, story: list) -> None:
        story.append(Paragraph("ACTIVITY TIMELINE", self.section_title_style))
        timeline = _build_activity_timeline(self.transaction)

        header = [
            Paragraph("DATE / TIME", self.timeline_header_style),
            Paragraph("EVENT", self.timeline_header_style),
            Paragraph("DETAILS", self.timeline_header_style),
            Paragraph("ACTOR", self.timeline_header_style),
        ]
        data = [header]

        if timeline:
            for item in timeline:
                data.append(
                    [
                        Paragraph(item["date"], self.cell_value_style),
                        Paragraph(item["event"], self.cell_label_style),
                        Paragraph(item["details"], self.cell_value_style),
                        Paragraph(item["actor"], self.cell_value_style),
                    ]
                )
        else:
            data.append(
                [
                    Paragraph("-", self.cell_value_style),
                    Paragraph("No Activity", self.cell_label_style),
                    Paragraph("No activities recorded for this transaction.", self.cell_value_style),
                    Paragraph("System", self.cell_value_style),
                ]
            )

        timeline_table = Table(data, colWidths=[1.4 * inch, 1.1 * inch, 3.6 * inch, 1.1 * inch], repeatRows=1)
        timeline_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                    ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#64748b")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(timeline_table)

    def generate(self) -> BytesIO:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=0.5 * inch,
            bottomMargin=0.45 * inch,
            leftMargin=0.5 * inch,
            rightMargin=0.5 * inch,
        )

        story: list = []
        self._build_header(story)
        self._build_details_section(story)
        self._build_timeline_section(story)

        doc.build(story)
        buffer.seek(0)
        return buffer


def build_cash_transaction_pdf_bytes(transaction: AccountingCashTransaction) -> bytes:
    """Render a single cash transaction detail sheet as PDF bytes."""
    school = resolve_tenant_school()
    pdf_buffer = CashTransactionPDF(transaction, school=school).generate()
    return pdf_buffer.getvalue()

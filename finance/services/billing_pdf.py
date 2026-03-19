"""
Student Billing Financial Statement PDF Generator

Generates professional W-2 style PDF statements for student billing.
Uses ReportLab for server-side PDF generation.
"""

from io import BytesIO
from typing import Optional, List, Dict
from decimal import Decimal
from urllib.parse import urlparse

from django.http import HttpResponse
from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    KeepTogether,
)

from students.models import Student
from django.utils import timezone
from common.services.pdf_components import build_pdf_header


class StudentBillingPDF:
    """Generate professional W-2 style student financial statement PDF"""

    def __init__(self, student: Student, school, enrollment):
        self.student = student
        self.school = school
        self.enrollment = enrollment
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles"""
        styles = getSampleStyleSheet()

        # School name style (large, bold, blue)
        self.school_name_style = ParagraphStyle(
            "SchoolName",
            parent=styles["Heading1"],
            fontSize=15,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1976d2"),
            alignment=TA_LEFT,
            spaceAfter=1,
            leftIndent=0,
        )

        # Contact info style (small, normal)
        self.contact_style = ParagraphStyle(
            "Contact",
            parent=styles["Normal"],
            fontSize=8,
            fontName="Helvetica",
            textColor=colors.HexColor("#424242"),
            alignment=TA_LEFT,
            leading=9,
            spaceAfter=0,
            leftIndent=0,
        )

        # Title style (centered, bold)
        self.title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=13,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1976d2"),
            alignment=TA_CENTER,
            spaceAfter=1,
        )

        # Section header style
        self.section_header_style = ParagraphStyle(
            "SectionHeader",
            parent=styles["Heading2"],
            fontSize=9,
            fontName="Courier-Bold",
            textColor=colors.black,
            alignment=TA_LEFT,
            spaceBefore=3,
            spaceAfter=2,
        )

        # Box label style (small, bold)
        self.box_label_style = ParagraphStyle(
            "BoxLabel",
            parent=styles["Normal"],
            fontSize=6.5,
            fontName="Courier-Bold",
            textColor=colors.black,
            alignment=TA_LEFT,
        )

        # Box value style (larger, normal)
        self.box_value_style = ParagraphStyle(
            "BoxValue",
            parent=styles["Normal"],
            fontSize=9,
            fontName="Courier",
            textColor=colors.black,
            alignment=TA_LEFT,
        )

    def _format_currency(self, amount: Optional[Decimal]) -> str:
        """Format amount as currency"""
        if amount is None:
            return "$0.00"
        return f"${amount:,.2f}"

    def _get_tenant_footer_url(self) -> str:
        """Return tenant URL in subdomain.maindomain format when possible."""
        schema_name = (getattr(self.school, "schema_name", "") or "").strip()
        if not schema_name:
            return ""

        frontend_domain = (getattr(settings, "FRONTEND_DOMAIN", "") or "").strip()
        if not frontend_domain:
            return schema_name

        domain_candidate = frontend_domain
        if "://" not in domain_candidate:
            domain_candidate = f"https://{domain_candidate}"

        parsed = urlparse(domain_candidate)
        hostname = (parsed.hostname or "").strip()
        port = parsed.port

        if not hostname:
            return schema_name

        labels = hostname.split(".")
        if len(labels) >= 3:
            main_domain = ".".join(labels[-2:])
        else:
            main_domain = hostname

        tenant_host = f"{schema_name}.{main_domain}"
        if port:
            tenant_host = f"{tenant_host}:{port}"

        return tenant_host

    def _build_header(self, story: List) -> None:
        """Build document header with school info and logo using shared component"""
        statement_date_text = f"Statement Date: {timezone.now().strftime('%m/%d/%Y')}"
        
        build_pdf_header(
            story=story,
            school=self.school,
            school_name_style=self.school_name_style,
            contact_style=self.contact_style,
            title_text="STUDENT FINANCIAL STATEMENT",
            title_style=self.title_style,
            show_statement_date=True,
            statement_date_text=statement_date_text,
            bottom_spacer_inches=0.04,
        )

    def _build_student_info(self, story: List) -> None:
        """Build a single student information box with three columns."""
        grade_level = self.enrollment.grade_level.name if self.enrollment and self.enrollment.grade_level else "N/A"
        section = self.enrollment.section.name if self.enrollment and self.enrollment.section else "N/A"
        academic_year = self.enrollment.academic_year.name if self.enrollment and self.enrollment.academic_year else "N/A"
        grade_class = f"{grade_level} {section}".strip() if section != "N/A" else grade_level

        student_label = Paragraph("STUDENT FULL NAME / ID", self.box_label_style)
        grade_class_label = Paragraph("GRADE CLASS", self.box_label_style)
        academic_year_label = Paragraph("ACADEMIC YEAR", self.box_label_style)

        student_value = Paragraph(
            f"{self.student.first_name} {self.student.last_name} (ID: {self.student.id_number or 'N/A'})",
            self.box_value_style,
        )

        data = [
            [
                student_label,
                grade_class_label,
                academic_year_label,
            ],
            [
                student_value,
                Paragraph(grade_class or "N/A", self.box_value_style),
                Paragraph(academic_year, self.box_value_style),
            ],
        ]

        details_table = Table(data, colWidths=[3.1 * inch, 2.55 * inch, 2.15 * inch])
        details_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, 0), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
                    ("TOPPADDING", (0, 1), (-1, 1), 5),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 5),
                ]
            )
        )
        story.append(details_table)
        story.append(Spacer(1, 0.1 * inch))

    def _build_financial_summary(self, story: List, billing_summary: Dict) -> None:
        """Build financial summary metrics with gross, concession, net, paid, and balance."""
        story.append(Paragraph("FINANCIAL SUMMARY", self.section_header_style))

        gross_total_bill = billing_summary.get("gross_total_bill", billing_summary.get("total_bill", 0))
        total_concession = billing_summary.get("total_concession", 0)
        net_total_bill = billing_summary.get("net_total_bill", billing_summary.get("total_bill", 0))
        paid = billing_summary.get("paid", 0)
        balance = billing_summary.get("balance", 0)

        summary_value_style = ParagraphStyle(
            "SummaryMetricValue",
            parent=self.box_value_style,
            fontSize=9,
            fontName="Courier-Bold",
            alignment=TA_CENTER,
        )

        summary_data = [
            [
                Paragraph("GROSS TOTAL BILL", self.box_label_style),
                Paragraph("CONCESSION", self.box_label_style),
                Paragraph("NET TOTAL BILL", self.box_label_style),
                Paragraph("TOTAL PAID", self.box_label_style),
                Paragraph("OUTSTANDING BALANCE", self.box_label_style),
            ],
            [
                Paragraph(
                    f'<b>{self._format_currency(gross_total_bill)}</b>',
                    summary_value_style,
                ),
                Paragraph(
                    f'<b><font color="#7e22ce">{self._format_currency(total_concession)}</font></b>',
                    summary_value_style,
                ),
                Paragraph(
                    f'<b><font color="#1d4ed8">{self._format_currency(net_total_bill)}</font></b>',
                    summary_value_style,
                ),
                Paragraph(
                    f'<b><font color="#2e7d32">{self._format_currency(paid)}</font></b>',
                    summary_value_style,
                ),
                Paragraph(
                    f'<b><font color="{"#d32f2f" if balance > 0 else "#2e7d32"}">{self._format_currency(balance)}</font></b>',
                    summary_value_style,
                ),
            ],
        ]

        summary_table = Table(summary_data, colWidths=[1.56 * inch] * 5)
        summary_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, 0), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
                    ("TOPPADDING", (0, 1), (-1, 1), 6),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
                ]
            )
        )
        story.append(summary_table)
        story.append(Spacer(1, 0.05 * inch))

        # Payment status box
        payment_status = billing_summary.get("payment_status", {})
        if payment_status:
            is_paid = payment_status.get("is_paid_in_full", False)
            is_on_time = payment_status.get("is_on_time", True)
            overdue_count = payment_status.get("overdue_count", 0)

            status_text = "PAID IN FULL" if is_paid else ("ON TRACK" if is_on_time else "OVERDUE")
            status_color = "#2e7d32" if is_paid else ("#000000" if is_on_time else "#d32f2f")

            if overdue_count > 0:
                status_display = f'<b><font color="{status_color}">{status_text}</font></b> ({overdue_count} overdue)'
            else:
                status_display = f'<b><font color="{status_color}">{status_text}</font></b>'

            status_data = [
                [Paragraph("PAYMENT STATUS", self.box_label_style)],
                [
                    Paragraph(
                        status_display,
                        ParagraphStyle("StatusValue", parent=self.box_value_style),
                    )
                ],
            ]

            status_table = Table(status_data, colWidths=[7.8 * inch])
            status_table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, 0), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
                        ("TOPPADDING", (0, 1), (-1, 1), 6),
                        ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
                    ]
                )
            )
            story.append(status_table)

        story.append(Spacer(1, 0.1 * inch))

    def _build_bill_breakdown(self, story: List, bill_items: List[Dict]) -> None:
        """Build bill breakdown table with KeepTogether to prevent page splitting"""
        if not bill_items:
            return

        section_elements = []
        section_elements.append(Paragraph("BILL BREAKDOWN", self.section_header_style))

        # Table data
        table_data = [["ITEM", "AMOUNT"]]
        total = Decimal(0)

        for item in bill_items:
            table_data.append([item["name"], self._format_currency(item["amount"])])
            total += item["amount"]

        table_data.append(["TOTAL", self._format_currency(total)])

        bill_table = Table(table_data, colWidths=[5.8 * inch, 2.0 * inch])
        bill_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (1, 0), colors.HexColor("#f0f0f0")),
                    ("BACKGROUND", (0, -1), (1, -1), colors.HexColor("#f0f0f0")),
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTNAME", (0, 0), (-1, -1), "Courier"),
                    ("FONTNAME", (0, 0), (-1, 0), "Courier-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Courier-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        section_elements.append(bill_table)
        
        # Wrap entire section with KeepTogether
        story.append(KeepTogether(section_elements))
        story.append(Spacer(1, 0.1 * inch))

    def _build_concession_breakdown(self, story: List, concessions: List[Dict]) -> None:
        """Build concession breakdown table when concessions exist."""
        if not concessions:
            return

        section_elements = []
        section_elements.append(Paragraph("CONCESSION BREAKDOWN", self.section_header_style))

        table_data = [["TARGET", "TYPE", "VALUE", "AMOUNT"]]

        for item in concessions:
            target = str(item.get("target", "entire_bill")).replace("_", " ").title()
            concession_type = str(item.get("concession_type", "flat")).title()
            value = item.get("value", 0)
            amount = item.get("amount", 0)

            value_label = f"{value}%" if item.get("concession_type") == "percentage" else self._format_currency(value)

            table_data.append([
                target,
                concession_type,
                value_label,
                self._format_currency(amount),
            ])

        concession_table = Table(table_data, colWidths=[2.8 * inch, 1.3 * inch, 1.6 * inch, 2.1 * inch])
        concession_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("ALIGN", (0, 0), (2, -1), "LEFT"),
                    ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTNAME", (0, 0), (-1, -1), "Courier"),
                    ("FONTNAME", (0, 0), (-1, 0), "Courier-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("TEXTCOLOR", (3, 1), (3, -1), colors.HexColor("#7e22ce")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        section_elements.append(concession_table)

        story.append(KeepTogether(section_elements))
        story.append(Spacer(1, 0.1 * inch))

    def _build_payment_plan(self, story: List, payment_plan: List[Dict]) -> None:
        """Build payment plan table with KeepTogether to prevent page splitting"""
        if not payment_plan:
            return

        section_elements = []
        section_elements.append(Paragraph("PAYMENT PLAN", self.section_header_style))

        # Table headers
        table_data = [
            [
                "INSTALLMENT",
                "DUE DATE",
                "AMOUNT DUE",
                "CUMULATIVE DUE",
                "CUMULATIVE PAID",
                "CUMULATIVE BALANCE",
            ]
        ]

        # Add rows
        for index, item in enumerate(payment_plan):
            ordinal = index + 1
            suffix = "st" if ordinal == 1 else "nd" if ordinal == 2 else "rd" if ordinal == 3 else "th"
            installment_name = f"{ordinal}{suffix} Installment"

            # Format date to MMM DD, YYYY
            payment_date = item.get("payment_date", "")
            if payment_date:
                from datetime import datetime
                try:
                    date_obj = datetime.fromisoformat(str(payment_date))
                    payment_date = date_obj.strftime("%b %d, %Y")
                except:
                    pass

            # Get percentages
            percentage = item.get("percentage", 0)
            cumulative_percentage = item.get("cumulative_percentage", 0)

            # Create styled paragraphs for amounts with percentages
            amount_style = ParagraphStyle(
                "AmountCell",
                parent=self.box_value_style,
                fontSize=8,
                alignment=TA_RIGHT,
            )

            amount_with_pct = Paragraph(
                f'{self._format_currency(item.get("amount", 0))}<br/><font size="6" >({percentage:.0f}% of total)</font>',
                amount_style
            )
            cumulative_with_pct = Paragraph(
                f'{self._format_currency(item.get("cumulative_amount_due", 0))}<br/><font size="6" >({cumulative_percentage:.0f}% of total)</font>',
                amount_style
            )

            table_data.append(
                [
                    installment_name,
                    payment_date,
                    amount_with_pct,
                    cumulative_with_pct,
                    self._format_currency(item.get("cumulative_paid", 0)),
                    self._format_currency(item.get("cumulative_balance", 0)),
                ]
            )

        payment_table = Table(
            table_data,
            colWidths=[1.5 * inch, 1.0 * inch, 1.2 * inch, 1.4 * inch, 1.4 * inch, 1.3 * inch],
        )
        payment_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTNAME", (0, 0), (-1, -1), "Courier"),
                    ("FONTNAME", (0, 0), (-1, 0), "Courier-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 7),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        section_elements.append(payment_table)
        
        # Wrap entire section with KeepTogether
        story.append(KeepTogether(section_elements))
        story.append(Spacer(1, 0.1 * inch))

    def _build_transaction_history(self, story: List, transactions: List) -> None:
        """Build transaction history table with KeepTogether to prevent page splitting"""
        if not transactions:
            return

        section_elements = []
        section_elements.append(Paragraph("TRANSACTION HISTORY", self.section_header_style))

        # Table headers
        table_data = [["DATE", "REFERENCE", "TYPE", "METHOD", "AMOUNT"]]

        # Add transaction rows
        for transaction in transactions:
            # Format date to MMM DD, YYYY
            transaction_date = transaction.get("date", "")
            if transaction_date:
                from datetime import datetime
                try:
                    date_obj = datetime.fromisoformat(str(transaction_date))
                    transaction_date = date_obj.strftime("%b %d, %Y")
                except:
                    pass

            table_data.append(
                [
                    transaction_date,
                    transaction.get("reference", "-") or "-",
                    transaction.get("type", {}).get("name", "-") if isinstance(transaction.get("type"), dict) else "-",
                    transaction.get("payment_method", {}).get("name", "-") if isinstance(transaction.get("payment_method"), dict) else "-",
                    self._format_currency(transaction.get("amount", 0)),
                ]
            )

        transaction_table = Table(
            table_data,
            colWidths=[1.0 * inch, 1.5 * inch, 1.8 * inch, 1.8 * inch, 1.7 * inch],
        )
        transaction_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("ALIGN", (0, 0), (3, -1), "LEFT"),
                    ("ALIGN", (4, 0), (4, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTNAME", (0, 0), (-1, -1), "Courier"),
                    ("FONTNAME", (0, 0), (-1, 0), "Courier-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 7),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        section_elements.append(transaction_table)
        
        # Wrap entire section with KeepTogether
        story.append(KeepTogether(section_elements))
        story.append(Spacer(1, 0.1 * inch))

    def _build_footer(self, story: List) -> None:
        """Build footer"""
        story.append(Spacer(1, 0.12 * inch))

        footer_style = ParagraphStyle(
            "Footer",
            parent=self.contact_style,
            alignment=TA_CENTER,
            fontSize=7,
            textColor=colors.gray,
        )

        tenant_url = self._get_tenant_footer_url()
        footer_note = "This is a computer-generated statement and does not require a signature."
        footer_text_value = (
            f"{footer_note}<br/>Portal: {tenant_url}"
            if tenant_url
            else footer_note
        )

        footer_text = Paragraph(footer_text_value, footer_style)
        story.append(footer_text)

    def generate(
        self, billing_summary: Dict, bill_items: List[Dict], payment_plan: List[Dict], transactions: List[Dict]
    ) -> BytesIO:
        """Generate the complete PDF financial statement"""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=0.3 * inch,
            bottomMargin=0.3 * inch,
            leftMargin=0.35 * inch,
            rightMargin=0.35 * inch,
        )
        story = []

        # Build document sections
        self._build_header(story)
        self._build_student_info(story)
        self._build_financial_summary(story, billing_summary)
        self._build_bill_breakdown(story, bill_items)
        self._build_concession_breakdown(story, billing_summary.get("concessions") or [])
        self._build_payment_plan(story, payment_plan)
        self._build_transaction_history(story, transactions)
        self._build_footer(story)

        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer


def generate_student_billing_pdf(
    student: Student,
    school,
    enrollment,
    billing_summary: Dict,
    bill_items: List[Dict],
    payment_plan: List[Dict],
    transactions: List[Dict],
) -> HttpResponse:
    """
    Generate and return HTTP response with student billing PDF.

    Args:
        student: Student instance
        school: Tenant/school instance used for PDF header branding
        enrollment: Enrollment instance
        billing_summary: Dictionary with total_bill, paid, balance, payment_status
        bill_items: List of bill items with name and amount
        payment_plan: List of payment plan installments
        transactions: List of transactions

    Returns:
        HttpResponse with PDF file
    """
    # Generate PDF
    pdf_generator = StudentBillingPDF(student, school, enrollment)
    pdf_buffer = pdf_generator.generate(billing_summary, bill_items, payment_plan, transactions)

    # Create HTTP response
    response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
    filename = f"{student.first_name}_{student.last_name}_Financial_Statement_{timezone.now().strftime('%Y-%m-%d')}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    return response

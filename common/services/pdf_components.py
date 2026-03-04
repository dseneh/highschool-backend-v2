"""
Reusable PDF components for consistent document generation across the application.
"""

from io import BytesIO
from typing import Optional, List
import logging

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    HRFlowable,
    Image as RLImage,
)

logger = logging.getLogger(__name__)


def get_school_logo(school, width: float = 1.0, height: float = 1.0) -> Optional[RLImage]:
    """
    Get school logo as ReportLab Image with multiple loading strategies.
    
    Args:
        school: School model instance
        width: Logo width in inches
        height: Logo height in inches
        
    Returns:
        RLImage instance or None if logo cannot be loaded
    """
    if not school.logo:
        return None

    try:
        logo_data = None

        # Strategy 1: Try opening via storage backend (handles S3/Local)
        try:
            with school.logo.open("rb") as f:
                logo_data = f.read()
        except Exception:
            pass

        # Strategy 2: Try fetching from URL if open failed (e.g. S3 signed URL issue)
        if not logo_data and hasattr(school.logo, "url"):
            try:
                import requests

                response = requests.get(school.logo.url, timeout=5)
                if response.status_code == 200:
                    logo_data = response.content
            except Exception:
                pass

        if logo_data:
            image_buffer = BytesIO(logo_data)
            logo = RLImage(
                image_buffer,
                width=width * inch,
                height=height * inch,
                kind="proportional",
            )
            return logo

    except Exception as e:
        logger.warning(f"Could not load school logo: {e}")

    return None


def build_pdf_header(
    story: List,
    school,
    school_name_style: ParagraphStyle,
    contact_style: ParagraphStyle,
    title_text: str,
    title_style: ParagraphStyle,
    show_statement_date: bool = False,
    statement_date_text: str = "",
) -> None:
    """
    Build a standardized PDF header with school logo, information, and title.
    
    Args:
        story: ReportLab story list to append elements to
        school: School model instance
        school_name_style: ParagraphStyle for school name
        contact_style: ParagraphStyle for contact information
        title_text: Document title text
        title_style: ParagraphStyle for title
        show_statement_date: Whether to show a statement date below title
        statement_date_text: Statement date text to display
    """
    # Get school logo
    logo = get_school_logo(school)

    # School name (large, bold, blue)
    school_name = Paragraph(school.name, school_name_style)

    # Address
    address_text = ""
    if school.address:
        address_text = school.address
    address_para = (
        Paragraph(address_text, contact_style) if address_text else None
    )

    # Contact info
    contact_elements = []

    # Email and website on same line
    email_website_parts = []
    if school.email:
        email_website_parts.append(f"Email: {school.email}")
    if school.website:
        email_website_parts.append(f"Website: {school.website}")

    if email_website_parts:
        email_website_text = "; ".join(email_website_parts)
        contact_elements.append(Paragraph(email_website_text, contact_style))

    # Phone and EMIS (if available)
    phone_emis_parts = []
    if school.phone:
        phone_text = f"Phone: {school.phone}"
        emis_text = (
            f"EMIS Number: {school.emis_number}"
            if hasattr(school, "emis_number") and school.emis_number
            else ""
        )

        # Combine with EMIS in red using HTML color tag
        if emis_text:
            combined_text = (
                phone_text + '; <font color="#d32f2f">' + emis_text + "</font>"
            )
        else:
            combined_text = phone_text

        if combined_text:
            contact_elements.append(Paragraph(combined_text, contact_style))

    # Create school info column content
    school_info_elements = []
    if school_name:
        school_info_elements.append(school_name)
    if address_para:
        school_info_elements.append(address_para)
    school_info_elements.extend(contact_elements)

    # Create header table: [Logo, School Info]
    header_data = [[logo if logo else "", school_info_elements]]

    # Create header table with same dimensions as report card
    header_table = Table(
        header_data, colWidths=[1.1 * inch, 6.9 * inch], hAlign="LEFT"
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),  # Logo column
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 4),  # School info column
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    story.append(header_table)
    story.append(Spacer(1, 0.02 * inch))

    # Add horizontal light blue line separator (matching report card)
    blue_line = HRFlowable(
        width="100%",
        thickness=0.5,
        lineCap="round",
        color=colors.HexColor("#90caf9"),  # Light blue
        spaceBefore=0.02 * inch,
        spaceAfter=0.02 * inch,
    )
    story.append(blue_line)

    # Title (centered, bold)
    story.append(Spacer(1, 0.1 * inch))
    title = Paragraph(title_text, title_style)
    story.append(title)

    # Optional statement date
    if show_statement_date and statement_date_text:
        date_style = ParagraphStyle(
            "StatementDate",
            parent=contact_style,
            alignment=TA_CENTER,
            fontSize=7,
        )
        date_para = Paragraph(statement_date_text, date_style)
        story.append(date_para)

    story.append(Spacer(1, 0.15 * inch))

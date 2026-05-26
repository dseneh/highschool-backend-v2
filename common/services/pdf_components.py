"""
Reusable PDF components for consistent document generation across the application.
"""

from io import BytesIO
from typing import Optional, List
import logging
import os

from django.conf import settings
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


def format_tenant_address(school) -> str:
    """Build a single-line mailing address from tenant address fields."""
    if not school:
        return ""

    line1 = (getattr(school, "address", None) or "").strip()
    locality_parts: List[str] = []
    for field in ("city", "state", "postal_code"):
        value = (getattr(school, field, None) or "").strip()
        if value:
            locality_parts.append(value)
    line2 = ", ".join(locality_parts)
    country = (getattr(school, "country", None) or "").strip()

    parts: List[str] = []
    if line1:
        parts.append(line1)
    if line2:
        parts.append(line2)
    if country and country.lower() not in line2.lower():
        parts.append(country)
    return ", ".join(parts)


def resolve_tenant_school(school=None):
    """
    Return the public-schema Tenant record for the current request schema.
    Pass ``school`` when the caller already resolved it.
    """
    if school is not None:
        return school

    try:
        from django.db import connection
        from django_tenants.utils import get_public_schema_name, schema_context
        from core.models import Tenant
    except Exception:
        return None

    schema_name = getattr(connection, "schema_name", None)
    if not schema_name or schema_name == get_public_schema_name():
        return None

    with schema_context(get_public_schema_name()):
        return Tenant.objects.filter(schema_name=schema_name).first()


def get_pdf_header_styles():
    """
    Standard paragraph styles for ``build_pdf_header`` (billing, grading, reports).
    Matches the styles used by ``StudentBillingPDF``.
    """
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()

    school_name_style = ParagraphStyle(
        "SchoolName",
        parent=styles["Heading1"],
        fontSize=15,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1976d2"),
        alignment=TA_LEFT,
        spaceAfter=1,
        leftIndent=0,
    )

    contact_style = ParagraphStyle(
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

    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=13,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1976d2"),
        alignment=TA_CENTER,
        spaceAfter=1,
    )

    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Helvetica",
        textColor=colors.HexColor("#424242"),
        alignment=TA_CENTER,
        leading=10,
        spaceAfter=4,
    )

    return school_name_style, contact_style, title_style, subtitle_style


def append_pdf_document_header(
    story: List,
    school,
    title_text: str,
    *,
    school_name_style: Optional[ParagraphStyle] = None,
    contact_style: Optional[ParagraphStyle] = None,
    title_style: Optional[ParagraphStyle] = None,
    show_statement_date: bool = False,
    statement_date_text: str = "",
    bottom_spacer_inches: float = 0.08,
    header_width_inches: float = 7.2,
) -> None:
    """Append the shared school logo / contact / title header to a PDF story."""
    default_school, default_contact, default_title, _ = get_pdf_header_styles()
    build_pdf_header(
        story=story,
        school=school,
        school_name_style=school_name_style or default_school,
        contact_style=contact_style or default_contact,
        title_text=title_text,
        title_style=title_style or default_title,
        show_statement_date=show_statement_date,
        statement_date_text=statement_date_text,
        bottom_spacer_inches=bottom_spacer_inches,
        header_width_inches=header_width_inches,
    )


def append_pdf_subtitle(story: List, text: str) -> None:
    """Centered subtitle line below the standard document header."""
    _, _, _, subtitle_style = get_pdf_header_styles()
    story.append(Paragraph(text, subtitle_style))


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
    if not school or not getattr(school, "logo", None):
        return None

    def iter_logo_paths() -> List[str]:
        candidates: List[str] = []

        try:
            direct_path = getattr(school.logo, "path", None)
            if direct_path:
                candidates.append(direct_path)
        except Exception:
            pass

        logo_name = getattr(school.logo, "name", "")
        if logo_name:
            media_root = str(settings.MEDIA_ROOT)
            candidates.extend(
                [
                    os.path.join(media_root, logo_name),
                    os.path.join(media_root, "public", logo_name),
                ]
            )

            schema_name = getattr(school, "schema_name", None)
            if schema_name:
                relative_path = logo_name
                tenant_prefix = f"tenants/{schema_name}/"
                if relative_path.startswith(tenant_prefix):
                    relative_path = relative_path[len(tenant_prefix):]
                candidates.append(os.path.join(media_root, schema_name, relative_path))

        deduped_candidates: List[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped_candidates:
                deduped_candidates.append(candidate)
        return deduped_candidates

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

        # Strategy 3: Try direct filesystem path for local media storage.
        if not logo_data:
            for logo_path in iter_logo_paths():
                try:
                    if os.path.exists(logo_path):
                        with open(logo_path, "rb") as f:
                            logo_data = f.read()
                        break
                except Exception:
                    continue

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
    bottom_spacer_inches: float = 0.08,
    header_width_inches: float = 7.2,
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
    # Size logo by configured tenant shape and keep the full header within page width.
    logo_width = 0.82
    logo_height = 0.82
    if getattr(school, "logo_shape", None) == "landscape":
        logo_width = 1.1
        logo_height = 0.62

    logo = get_school_logo(school, width=logo_width, height=logo_height) if school else None

    # School name (large, bold, blue)
    school_name = (
        Paragraph(school.name, school_name_style) if school and school.name else None
    )

    # Address (street + city/state/postal + country when available)
    address_text = format_tenant_address(school) if school else ""
    address_para = (
        Paragraph(address_text, contact_style) if address_text else None
    )

    # Contact info
    contact_elements = []

    # Email and website on same line
    email_website_parts = []
    if school and school.email:
        email_website_parts.append(f"Email: {school.email}")
    if school and school.website:
        email_website_parts.append(f"Website: {school.website}")

    if email_website_parts:
        email_website_text = "; ".join(email_website_parts)
        contact_elements.append(Paragraph(email_website_text, contact_style))

    # Phone and EMIS (if available)
    phone_emis_parts = []
    if school and school.phone:
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

    info_width = max(4.0, float(header_width_inches) - 1.0)
    header_table = Table(
        header_data,
        colWidths=[1.0 * inch, info_width * inch],
        hAlign="LEFT",
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),  # Logo column
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 6),  # School info column
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
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
    story.append(Spacer(1, 0.05 * inch))
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

    story.append(Spacer(1, max(0.0, bottom_spacer_inches) * inch))

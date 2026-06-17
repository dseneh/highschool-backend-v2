"""Official multi-year student transcript PDF generation."""

from __future__ import annotations

import os
from io import BytesIO
from typing import List, Optional

from django.conf import settings
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from common.services.pdf_components import get_school_logo, resolve_tenant_school
from grading.services.transcript_data import (
    TranscriptDataService,
    TranscriptGradeScaleEntry,
    TranscriptPayload,
)
from students.models import Student


NAVY = colors.HexColor("#1a365d")
HIGHLIGHT = colors.HexColor("#ebf8ff")
BORDER_LIGHT = colors.HexColor("#cbd5e1")
BORDER_STRONG = colors.HexColor("#64748b")
MUTED = colors.HexColor("#616161")

# Full content width on letter with 0.55" side margins
CONTENT_WIDTH = 7.4 * inch
SUPPLEMENT_COL_WIDTH = CONTENT_WIDTH / 3
GRID_COL_GAP = 6  # right padding between supplemental columns (points)
PANEL_PADDING = 8
PANEL_WIDTH = SUPPLEMENT_COL_WIDTH - GRID_COL_GAP
PANEL_INNER_WIDTH = PANEL_WIDTH - (2 * PANEL_PADDING)
SCALE_SPLIT_GAP = 4
SCALE_HALF_WIDTH = (PANEL_INNER_WIDTH - SCALE_SPLIT_GAP) / 2
GRID_LINE_WIDTH = 0.5
PANEL_BORDER_WIDTH = 0.75
PANEL_GAP = 0.1 * inch


class OfficialTranscriptPDF:
    """Render an official transcript PDF from a structured payload."""

    def __init__(self, payload: TranscriptPayload, school=None):
        self.payload = payload
        self.school = school
        self.styles = getSampleStyleSheet()
        self._setup_styles()

    def _setup_styles(self) -> None:
        self.title_style = ParagraphStyle(
            "TranscriptTitle",
            parent=self.styles["Heading1"],
            fontSize=14,
            textColor=NAVY,
            fontName="Helvetica-Bold",
            alignment=TA_RIGHT,
            leading=16,
        )
        self.meta_value_style = ParagraphStyle(
            "MetaValue",
            parent=self.styles["Normal"],
            fontSize=8,
            fontName="Helvetica",
            textColor=colors.black,
            alignment=TA_RIGHT,
            leading=10,
        )
        self.section_title_style = ParagraphStyle(
            "SectionTitle",
            parent=self.styles["Normal"],
            fontSize=10,
            fontName="Helvetica-Bold",
            textColor=NAVY,
            leading=12,
        )
        self.label_style = ParagraphStyle(
            "Label",
            parent=self.styles["Normal"],
            fontSize=8,
            fontName="Helvetica-Bold",
            textColor=MUTED,
            leading=10,
        )
        self.value_style = ParagraphStyle(
            "Value",
            parent=self.styles["Normal"],
            fontSize=8,
            fontName="Helvetica",
            textColor=colors.black,
            leading=10,
        )
        self.table_header_style = ParagraphStyle(
            "TableHeader",
            parent=self.styles["Normal"],
            fontSize=7,
            fontName="Helvetica-Bold",
            textColor=colors.white,
            alignment=TA_CENTER,
            leading=9,
        )
        self.table_cell_style = ParagraphStyle(
            "TableCell",
            parent=self.styles["Normal"],
            fontSize=7,
            fontName="Helvetica",
            textColor=colors.black,
            leading=9,
        )
        self.table_cell_center_style = ParagraphStyle(
            "TableCellCenter",
            parent=self.table_cell_style,
            alignment=TA_CENTER,
        )
        self.footnote_style = ParagraphStyle(
            "Footnote",
            parent=self.styles["Normal"],
            fontSize=6,
            fontName="Helvetica-Oblique",
            textColor=MUTED,
            leading=8,
        )
        self.footer_style = ParagraphStyle(
            "Footer",
            parent=self.styles["Normal"],
            fontSize=8,
            fontName="Helvetica",
            textColor=MUTED,
            leading=11,
        )
        self.footer_label_style = ParagraphStyle(
            "FooterLabel",
            parent=self.label_style,
            fontSize=7,
            textColor=MUTED,
            leading=9,
        )
        self.school_name_style = ParagraphStyle(
            "SchoolName",
            parent=self.styles["Normal"],
            fontSize=14,
            textColor=NAVY,
            fontName="Helvetica-Bold",
            leading=16,
            alignment=TA_LEFT,
        )
        self.contact_style = ParagraphStyle(
            "Contact",
            parent=self.styles["Normal"],
            fontSize=8,
            textColor=colors.black,
            fontName="Helvetica",
            leading=10,
            alignment=TA_LEFT,
        )

    def generate(self) -> BytesIO:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            leftMargin=0.55 * inch,
            rightMargin=0.55 * inch,
        )
        story: List = []
        self._build_header(story)
        self._build_profile_section(story)
        self._build_academic_record(story)
        self._build_supplemental_grid(story)
        self._build_footer(story)
        doc.build(story)
        buffer.seek(0)
        return buffer

    def _build_header(self, story: List) -> None:
        meta_rows = [
            [Paragraph("OFFICIAL TRANSCRIPT", self.title_style)],
            [
                Paragraph(
                    f"<b>Transcript ID:</b> {self.payload.transcript_id}",
                    self.meta_value_style,
                )
            ],
            [
                Paragraph(
                    f"<b>Date Issued:</b> {self.payload.date_issued}",
                    self.meta_value_style,
                )
            ],
        ]
        if self.payload.emis_number:
            meta_rows.append(
                [
                    Paragraph(
                        f'<b>EMIS Number:</b> <font color="#d32f2f">{self.payload.emis_number}</font>',
                        self.meta_value_style,
                    )
                ]
            )

        # Calculate header widths to use full CONTENT_WIDTH
        right_meta_width = 2.5 * inch
        left_section_width = CONTENT_WIDTH - right_meta_width
        logo_width = 0.9 * inch
        school_info_width = left_section_width - logo_width
        
        left_logo_school = Table(
            [[get_school_logo(self.school, 0.8, 0.8) or "", self._school_info_block()]],
            colWidths=[logo_width, school_info_width],
        )
        left_logo_school.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )

        right_meta = Table(
            [[row[0]] for row in meta_rows],
            colWidths=[right_meta_width],
        )
        right_meta.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )

        top_header = Table(
            [[left_logo_school, right_meta]],
            colWidths=[left_section_width, right_meta_width],
        )
        top_header.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story.append(top_header)
        story.append(Spacer(1, 0.06 * inch))
        story.append(
            HRFlowable(
                width=CONTENT_WIDTH,
                thickness=2,
                color=NAVY,
                spaceBefore=0,
                spaceAfter=0.08 * inch,
            )
        )

    def _school_info_block(self) -> List:
        elements = []
        if self.payload.school_name:
            elements.append(Paragraph(self.payload.school_name.upper(), self.school_name_style))
        if self.payload.school_address:
            elements.append(Paragraph(self.payload.school_address, self.contact_style))
        contact_parts = []
        if self.payload.school_phone:
            contact_parts.append(f"Phone: {self.payload.school_phone}")
        if self.payload.school_email:
            contact_parts.append(f"Email: {self.payload.school_email}")
        if self.payload.school_website:
            contact_parts.append(f"Website: {self.payload.school_website}")
        if contact_parts:
            elements.append(Paragraph(" · ".join(contact_parts), self.contact_style))
        return elements

    def _get_student_photo(self) -> Optional[RLImage]:
        photo_path = self.payload.photo_path
        if not photo_path:
            return None

        candidates = [photo_path]
        if not os.path.isabs(photo_path):
            candidates.append(os.path.join(str(settings.MEDIA_ROOT), photo_path))

        for path in candidates:
            try:
                if os.path.exists(path):
                    return RLImage(path, width=1.05 * inch, height=1.05 * inch)
            except Exception:
                continue
        return None

    def _build_profile_section(self, story: List) -> None:
        photo = self._get_student_photo()
        photo_cell = photo if photo else ""

        field_label_style = ParagraphStyle(
            "ProfileFieldLabel",
            parent=self.value_style,
            fontName="Helvetica-Bold",
            textColor=colors.black,
            leading=12,
        )
        field_value_style = ParagraphStyle(
            "ProfileFieldValue",
            parent=self.value_style,
            leading=12,
        )
        summary_label_style = ParagraphStyle(
            "SummaryLabel",
            parent=self.value_style,
            textColor=NAVY,
            leading=12,
        )
        summary_value_style = ParagraphStyle(
            "SummaryValue",
            parent=self.value_style,
            alignment=TA_RIGHT,
            leading=12,
        )

        name_para = Paragraph(
            self.payload.student_full_name,
            ParagraphStyle(
                "StudentName",
                parent=self.value_style,
                fontSize=12,
                fontName="Helvetica-Bold",
                textColor=NAVY,
                leading=14,
            ),
        )

        profile_fields = [
            ("Student ID:", self.payload.student_id_number),
            ("Date of Birth:", self.payload.date_of_birth or "-"),
            ("Grade Level:", self.payload.grade_level or "-"),
            ("Graduation Year:", self.payload.graduation_year or "-"),
            ("Section:", self.payload.current_section or "-"),
            ("Date Enrolled:", self.payload.date_enrolled or "-"),
        ]
        fields_table = Table(
            [
                [
                    Paragraph(label, field_label_style),
                    Paragraph(value, field_value_style),
                ]
                for label, value in profile_fields
            ],
            colWidths=[1.15 * inch, 1.95 * inch],
        )
        fields_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )

        info_stack = Table(
            [[name_para], [Spacer(1, 0.06 * inch)], [fields_table]],
            colWidths=[3.1 * inch],
        )
        info_stack.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )

        summary_title = Paragraph(
            "Cumulative Summary",
            ParagraphStyle(
                "SummaryTitle",
                parent=self.section_title_style,
                fontSize=10,
                leading=12,
            ),
        )
        summary_lines = [
            ("Cumulative Average:", self._format_pct(self.payload.cumulative_average)),
            ("Subjects Completed:", str(self.payload.total_subjects)),
            ("Class Rank:", self.payload.class_rank or "-"),
            ("Percentile Rank:", self.payload.percentile_rank or "-"),
        ]
        summary_fields = Table(
            [
                [
                    Paragraph(label, summary_label_style),
                    Paragraph(value, summary_value_style),
                ]
                for label, value in summary_lines
            ],
            colWidths=[1.35 * inch, 0.9 * inch],
        )
        summary_fields.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )

        summary_stack = Table(
            [[summary_title], [Spacer(1, 0.06 * inch)], [summary_fields]],
            colWidths=[2.25 * inch],
        )
        summary_stack.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )

        profile_table = Table(
            [[photo_cell, info_stack, summary_stack]],
            colWidths=[1.4 * inch, 3.4 * inch, 2.6 * inch],
            rowHeights=None,
        )
        profile_table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), PANEL_BORDER_WIDTH, BORDER_LIGHT),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f8fa")),
                    ("LINEAFTER", (0, 0), (0, 0), PANEL_BORDER_WIDTH, BORDER_LIGHT),
                    ("LINEAFTER", (1, 0), (1, 0), PANEL_BORDER_WIDTH, BORDER_LIGHT),
                    ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
                    ("VALIGN", (1, 0), (-1, 0), "TOP"),
                    ("ALIGN", (0, 0), (0, 0), "CENTER"),
                    ("LEFTPADDING", (0, 0), (0, 0), 10),
                    ("RIGHTPADDING", (0, 0), (0, 0), 10),
                    ("LEFTPADDING", (1, 0), (1, 0), 6),
                    ("RIGHTPADDING", (1, 0), (1, 0), 10),
                    ("LEFTPADDING", (2, 0), (2, 0), 12),
                    ("RIGHTPADDING", (2, 0), (2, 0), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(profile_table)
        story.append(Spacer(1, 0.12 * inch))

    def _build_academic_record(self, story: List) -> None:
        story.append(Paragraph("Academic Record", self.section_title_style))
        story.append(Spacer(1, 0.04 * inch))

        if not self.payload.subject_rows:
            # Fallback: no approved academic records
            empty_table = Table(
                [
                    [Paragraph("Subject Code", self.table_header_style), Paragraph("Subject Name", self.table_header_style)],
                    [Paragraph("No approved academic records on file.", self.table_cell_style), ""],
                ],
                colWidths=[0.85 * inch, 6.55 * inch],
                repeatRows=1,
            )
            empty_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), GRID_LINE_WIDTH, BORDER_STRONG),
                    ("BOX", (0, 0), (-1, -1), PANEL_BORDER_WIDTH, BORDER_STRONG),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ])
            )
            story.append(empty_table)
            story.append(Spacer(1, 0.1 * inch))
            return

        # Build the new pivoted table: subjects as rows, years as columns
        num_years = len(self.payload.year_columns)
        
        # Column widths: Subject Code, Subject Name, then 2 sub-columns per year (Score, Grade), then 2 for Final Avg
        # Calculate to use full CONTENT_WIDTH
        subject_code_width = 0.7 * inch
        subject_name_width = 2.0 * inch
        
        # Remaining width distributed across year columns and final avg (each has 2 sub-columns)
        num_grade_columns = (num_years + 1) * 2  # +1 for Final Avg
        remaining_width = CONTENT_WIDTH - subject_code_width - subject_name_width
        grade_col_width = remaining_width / num_grade_columns
        
        col_widths = [subject_code_width, subject_name_width]
        for _ in range(num_years):
            col_widths.extend([grade_col_width, grade_col_width])  # Score, Grade
        col_widths.extend([grade_col_width, grade_col_width])  # Final Avg Score, Grade

        # Header row 1: "Subject Code", "Subject Name", each year name (colspan 2), "Final Avg" (colspan 2)
        header_row_1 = [
            Paragraph("Subject Code", self.table_header_style),
            Paragraph("Subject Name", self.table_header_style),
        ]
        for year_col in self.payload.year_columns:
            header_row_1.append(
                Paragraph(
                    f"{year_col.academic_year_name}<br/>{year_col.grade_level_name}",
                    self.table_header_style,
                )
            )
            header_row_1.append("")  # Placeholder for colspan
        header_row_1.append(Paragraph("Final Avg", self.table_header_style))
        header_row_1.append("")  # Placeholder for colspan

        # Header row 2: empty for Subject Code/Name, then "Score" and "Grade" for each year, then for Final Avg
        header_row_2 = ["", ""]
        for _ in self.payload.year_columns:
            header_row_2.extend([
                Paragraph("Score", self.table_header_style),
                Paragraph("Grade", self.table_header_style),
            ])
        header_row_2.extend([
            Paragraph("Score", self.table_header_style),
            Paragraph("Grade", self.table_header_style),
        ])

        table_data = [header_row_1, header_row_2]

        # Data rows
        for subject_row in self.payload.subject_rows:
            row_data = [
                Paragraph(subject_row.subject_code, self.table_cell_center_style),
                Paragraph(subject_row.subject_name, self.table_cell_style),
            ]
            for year_col in self.payload.year_columns:
                grade_data = subject_row.year_grades.get(year_col.academic_year_name)
                if grade_data:
                    pct, letter = grade_data
                    row_data.append(Paragraph(self._format_score(pct), self.table_cell_center_style))
                    row_data.append(Paragraph(self._format_letter(letter), self.table_cell_center_style))
                else:
                    row_data.append(Paragraph("-", self.table_cell_center_style))
                    row_data.append(Paragraph("-", self.table_cell_center_style))
            
            # Final average
            row_data.append(Paragraph(self._format_score(subject_row.final_average), self.table_cell_center_style))
            row_data.append(Paragraph(self._format_letter(subject_row.final_average_letter), self.table_cell_center_style))
            
            table_data.append(row_data)

        # Build span commands for headers
        span_commands = []
        
        # Span Subject Code and Subject Name vertically (rows 0-1)
        span_commands.append(("SPAN", (0, 0), (0, 1)))  # Subject Code
        span_commands.append(("SPAN", (1, 0), (1, 1)))  # Subject Name
        
        # Span year names and Final Avg horizontally across Score/Grade columns
        col_idx = 2  # Start after Subject Code and Subject Name
        for _ in self.payload.year_columns:
            span_commands.append(("SPAN", (col_idx, 0), (col_idx + 1, 0)))  # Span year name across Score and Grade
            col_idx += 2
        span_commands.append(("SPAN", (col_idx, 0), (col_idx + 1, 0)))  # Span "Final Avg" across Score and Grade

        table = Table(table_data, colWidths=col_widths, repeatRows=2)
        table.setStyle(self._academic_table_style_pivoted(span_commands))
        story.append(table)

        story.append(Spacer(1, 0.04 * inch))
        story.append(
            Paragraph(
                f"* Cumulative average and rank reflect approved and verified "
                f"grades through {self.payload.date_issued}.",
                self.footnote_style,
            )
        )
        story.append(Spacer(1, 0.1 * inch))

    def _academic_table_style_pivoted(self, span_commands: list) -> TableStyle:
        """Table style for the new pivoted subject-based table."""
        style_commands = [
            # Header styling (rows 0 and 1)
            ("BACKGROUND", (0, 0), (-1, 1), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 1), colors.white),
            # Grid and borders
            ("GRID", (0, 0), (-1, -1), GRID_LINE_WIDTH, BORDER_STRONG),
            ("BOX", (0, 0), (-1, -1), PANEL_BORDER_WIDTH, BORDER_STRONG),
            # Alignment
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (1, 2), (1, -1), "LEFT"),  # Subject Name column left-aligned
            # Padding
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        style_commands.extend(span_commands)
        return TableStyle(style_commands)

    def _panel_table_style(self) -> TableStyle:
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), HIGHLIGHT),
            ("BOX", (0, 0), (-1, -1), PANEL_BORDER_WIDTH, BORDER_LIGHT),
            ("LEFTPADDING", (0, 0), (-1, -1), PANEL_PADDING),
            ("RIGHTPADDING", (0, 0), (-1, -1), PANEL_PADDING),
            ("TOPPADDING", (0, 0), (0, 0), 6),
            ("BOTTOMPADDING", (0, 0), (0, 0), 6),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        return TableStyle(commands)

    def _panel_table_style_two_column(self) -> TableStyle:
        """Style for two-column panels with right-aligned values."""
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), HIGHLIGHT),
            ("SPAN", (0, 0), (-1, 0)),  # Span header across both columns
            ("BOX", (0, 0), (-1, -1), PANEL_BORDER_WIDTH, BORDER_LIGHT),
            ("LEFTPADDING", (0, 0), (-1, -1), PANEL_PADDING),
            ("RIGHTPADDING", (0, 0), (-1, -1), PANEL_PADDING),
            ("TOPPADDING", (0, 0), (0, 0), 6),
            ("BOTTOMPADDING", (0, 0), (0, 0), 6),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 1), (0, -1), "LEFT"),  # Labels left-aligned
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Values right-aligned
        ]
        return TableStyle(commands)

    def _build_split_grade_scale_table(self) -> Table:
        """Grading scale split into two side-by-side columns (50/50)."""
        entries = list(self.payload.grade_scale)
        if not entries:
            entries = [
                TranscriptGradeScaleEntry("-", 0, 0),
            ]

        midpoint = (len(entries) + 1) // 2
        left_entries = entries[:midpoint]
        right_entries = entries[midpoint:]

        def _mini_scale_table(items: list[TranscriptGradeScaleEntry]) -> Table:
            mini_label_style = ParagraphStyle(
                "ScaleMiniLabel",
                parent=self.label_style,
                fontSize=7,
                leading=8,
            )
            mini_cell_style = ParagraphStyle(
                "ScaleMiniCell",
                parent=self.table_cell_center_style,
                fontSize=7,
                leading=8,
            )
            rows = [
                [
                    Paragraph("<b>Letter</b>", mini_label_style),
                    Paragraph("<b>Range %</b>", mini_label_style),
                ]
            ]
            for entry in items:
                if entry.letter == "-":
                    rows.append(
                        [
                            Paragraph("-", mini_cell_style),
                            Paragraph("Not configured", mini_cell_style),
                        ]
                    )
                else:
                    rows.append(
                        [
                            Paragraph(entry.letter, mini_cell_style),
                            Paragraph(
                                f"{entry.min_percentage:.0f}–{entry.max_percentage:.0f}",
                                mini_cell_style,
                            ),
                        ]
                    )
            letter_col = SCALE_HALF_WIDTH * 0.34
            range_col = SCALE_HALF_WIDTH - letter_col
            table = Table(
                rows,
                colWidths=[letter_col, range_col],
            )
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), GRID_LINE_WIDTH, BORDER_LIGHT),
                        ("BACKGROUND", (0, 0), (-1, 0), HIGHLIGHT),
                        ("LEFTPADDING", (0, 0), (-1, -1), 2),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]
                )
            )
            return table

        split = Table(
            [[_mini_scale_table(left_entries), _mini_scale_table(right_entries)]],
            colWidths=[SCALE_HALF_WIDTH, SCALE_HALF_WIDTH],
        )
        split.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (0, 0), SCALE_SPLIT_GAP),
                    ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ]
            )
        )

        rows = [
            [Paragraph("Grading Scale", self.section_title_style)],
            [split],
        ]
        wrapper = Table(rows, colWidths=[PANEL_WIDTH])
        wrapper.setStyle(self._panel_table_style())
        return wrapper

    def _build_honors_table(self) -> Table:
        right_align_style = ParagraphStyle(
            "HonorValue",
            parent=self.value_style,
            alignment=TA_RIGHT,
        )
        rows = [[Paragraph("Honors &amp; Distinctions", self.section_title_style)]]
        if self.payload.honors:
            for honor in self.payload.honors:
                rows.append([Paragraph(f"• {honor}", right_align_style)])
        else:
            rows.append([Paragraph("None recorded", right_align_style)])

        table = Table(rows, colWidths=[PANEL_WIDTH])
        table.setStyle(self._panel_table_style())
        return table

    def _build_academic_standing_table(self) -> Table:
        label_width = PANEL_WIDTH * 0.60
        value_width = PANEL_WIDTH * 0.40
        
        rows = [
            [Paragraph("Academic Standing", self.section_title_style), ""],
            [
                Paragraph("<b>Grade Level:</b>", self.value_style),
                Paragraph(self.payload.grade_level or '-', self.value_style),
            ],
            [
                Paragraph("<b>Section:</b>", self.value_style),
                Paragraph(self.payload.current_section or '-', self.value_style),
            ],
            [
                Paragraph("<b>Graduation Year:</b>", self.value_style),
                Paragraph(self.payload.graduation_year or '-', self.value_style),
            ],
            [
                Paragraph("<b>Date Enrolled:</b>", self.value_style),
                Paragraph(self.payload.date_enrolled or '-', self.value_style),
            ],
        ]
        table = Table(rows, colWidths=[label_width, value_width])
        table.setStyle(self._panel_table_style_two_column())
        return table

    def _build_supplemental_grid(self, story: List) -> None:
        scale_table = self._build_split_grade_scale_table()
        honors_table = self._build_honors_table()
        standing_table = self._build_academic_standing_table()

        grid = Table(
            [[scale_table, standing_table, honors_table]],
            colWidths=[SUPPLEMENT_COL_WIDTH, SUPPLEMENT_COL_WIDTH, SUPPLEMENT_COL_WIDTH],
        )
        grid.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (0, 0), GRID_COL_GAP),
                    ("RIGHTPADDING", (1, 0), (1, 0), GRID_COL_GAP),
                ]
            )
        )
        story.append(grid)
        story.append(Spacer(1, 0.14 * inch))

    def _build_footer(self, story: List) -> None:
        story.append(
            HRFlowable(
                width="100%",
                thickness=1,
                color=BORDER_LIGHT,
                spaceBefore=0,
                spaceAfter=0.12 * inch,
            )
        )

        def _signature_block(label: str, name: str, title: str) -> Table:
            line = Table([[""]], colWidths=[1.75 * inch], rowHeights=[12])
            line.setStyle(
                TableStyle(
                    [
                        ("LINEBELOW", (0, 0), (-1, -1), PANEL_BORDER_WIDTH, BORDER_LIGHT),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ]
                )
            )
            block = Table(
                [
                    [Paragraph(label, self.footer_label_style)],
                    [Spacer(1, 0.04 * inch)],
                    [line],
                    [Paragraph(name, self.footer_style)],
                    [Paragraph(title, self.footer_style)] if title else [Spacer(1, 0)],
                ],
                colWidths=[1.75 * inch],
            )
            block.setStyle(
                TableStyle(
                    [
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ]
                )
            )
            return block

        verify_url = (
            f"https://verify.ezyschool.app/transcript/{self.payload.transcript_id}"
            if self.payload.transcript_id
            else ""
        )
        qr_code = (
            createBarcodeDrawing("QR", value=verify_url, width=0.82 * inch, height=0.82 * inch)
            if verify_url
            else Paragraph("-", self.value_style)
        )
        verify_text = Table(
            [
                [Paragraph("Verify This Transcript", self.footer_label_style)],
                [
                    Paragraph(
                        "Scan the QR code or use the verification link below.",
                        self.footer_style,
                    )
                ],
                [Paragraph(verify_url or "-", self.footer_style)],
            ],
            colWidths=[1.45 * inch],
        )
        verify_text.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        verify_block = Table(
            [[verify_text, qr_code]],
            colWidths=[1.45 * inch, 0.9 * inch],
        )
        verify_block.hAlign = "RIGHT"
        verify_block.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )

        secure_badge_path = os.path.join(
            str(settings.BASE_DIR), "media", "images", "secure.png"
        )
        seal = None
        if os.path.exists(secure_badge_path):
            seal = RLImage(secure_badge_path, width=0.72 * inch, height=0.72 * inch)
        if not seal:
            seal = get_school_logo(self.school, 0.72, 0.72) or Paragraph("-", self.value_style)
        seal_block = Table([[seal]], colWidths=[0.75 * inch], rowHeights=[0.75 * inch])
        seal_block.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )

        footer = Table(
            [
                [
                    _signature_block(
                        f"{self.payload.signatory_title or 'Principal'} Signature",
                        self.payload.signatory_name or "School Principal",
                        self.payload.signatory_title or "Principal",
                    ),
                    _signature_block(
                        f"{self.payload.secondary_signatory_title or 'Registrar'} Signature",
                        self.payload.secondary_signatory_name or "School Registrar",
                        self.payload.secondary_signatory_title or "Registrar",
                    ),
                    verify_block,
                    seal_block,
                ]
            ],
            colWidths=[1.8 * inch, 1.8 * inch, 2.8 * inch, 0.95 * inch],
        )
        footer.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                    ("ALIGN", (3, 0), (3, 0), "RIGHT"),
                    ("LEFTPADDING", (3, 0), (3, 0), 4),
                ]
            )
        )
        story.append(footer)
        story.append(Spacer(1, 0.08 * inch))
        story.append(Paragraph(f"<b>Notes:</b> {self.payload.disclaimer}", self.footer_style))

    @staticmethod
    def _format_pct(value: Optional[float]) -> str:
        if value is None:
            return "-"
        return f"{value:.1f}%"

    @staticmethod
    def _format_letter(letter: Optional[str]) -> str:
        if letter and letter != "N/A":
            return letter
        return "-"

    @staticmethod
    def _format_score(percentage: Optional[float]) -> str:
        if percentage is None:
            return "-"
        return f"{percentage:.1f}%"


def build_official_transcript_pdf_bytes(student: Student) -> bytes:
    """Build official transcript PDF bytes for a student."""
    payload = TranscriptDataService.build(student)
    school = resolve_tenant_school(getattr(student, "school", None))
    pdf = OfficialTranscriptPDF(payload, school=school)
    return pdf.generate().getvalue()

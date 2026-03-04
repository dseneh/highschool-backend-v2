"""
PDF Report Generation Service for Student Grade Reports

This module provides optimized PDF generation for student report cards
with professional formatting and efficient data retrieval.
"""

from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Union

from django.conf import settings
from django.http import HttpResponse
from django.db.models import Max
from django.core.cache import cache
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image as RLImage,
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from academics.models import AcademicYear, MarkingPeriod
from students.models import Student, Enrollment
from grading.models import GradeBook, Grade
from grading.services.ranking import RankingService
from grading.utils import (
    calculate_marking_period_percentage,
    calculate_student_overall_average,
    get_letter_grade,
)
from common.services.pdf_components import build_pdf_header


class StudentReportCardPDF:
    """
    Generate professional student report card PDFs.
    Optimized for performance with efficient queries and caching.
    """

    def __init__(
        self, student: Student, academic_year: AcademicYear, enrollment: Enrollment
    ):
        self.student = student
        self.academic_year = academic_year
        self.enrollment = enrollment
        self.school = student.school

        # Get accumulation setting
        self.cumulative_average_calculation = True
        try:
            if hasattr(self.school, "grading_settings"):
                self.cumulative_average_calculation = (
                    self.school.grading_settings.cumulative_average_calculation
                )
        except Exception:
            # Fallback to default behavior (True) if settings table/object is missing or DB error
            pass

        # Initialize styles
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

        # Cache for grade data
        self._grade_data_cache = None

    def _setup_custom_styles(self):
        """Setup custom paragraph styles for the report"""
        # Title style
        self.title_style = ParagraphStyle(
            "ReportTitle",
            parent=self.styles["Heading1"],
            fontSize=16,
            textColor=colors.HexColor("#1a237e"),
            spaceAfter=10,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
        )

        # Student info label style
        self.label_style = ParagraphStyle(
            "InfoLabel",
            parent=self.styles["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#424242"),
            fontName="Helvetica-Bold",
            leading=11,
        )

        # Student info value style
        self.value_style = ParagraphStyle(
            "InfoValue",
            parent=self.styles["Normal"],
            fontSize=9,
            textColor=colors.black,
            fontName="Helvetica",
            leading=11,
        )

        # Grade value styles
        # Red: < 70
        self.grade_style_red = ParagraphStyle(
            "GradeValueRed",
            parent=self.styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#d32f2f"),  # Red
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
            leading=10,
        )

        # Green: >= 70 and < 90
        self.grade_style_green = ParagraphStyle(
            "GradeValueGreen",
            parent=self.styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#388e3c"),  # Green
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
            leading=10,
        )

        # Blue: >= 90
        self.grade_style_blue = ParagraphStyle(
            "GradeValueBlue",
            parent=self.styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#1976d2"),  # Blue
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
            leading=10,
        )

        # Rank value style (bold black)
        self.rank_style = ParagraphStyle(
            "RankValue",
            parent=self.styles["Normal"],
            fontSize=8,
            textColor=colors.black,
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
            leading=10,
        )

        # School name style (large, bold, blue)
        self.school_name_style = ParagraphStyle(
            "SchoolName",
            parent=self.styles["Normal"],
            fontSize=14,
            textColor=colors.HexColor("#1976d2"),  # Blue color
            fontName="Helvetica-Bold",
            leading=16,
            alignment=TA_LEFT,
            spaceAfter=6,  # Add margin below school name
        )

        # Contact info style (normal, left-aligned)
        self.contact_style = ParagraphStyle(
            "ContactInfo",
            parent=self.styles["Normal"],
            fontSize=8,
            textColor=colors.black,
            fontName="Helvetica",
            leading=10,
            alignment=TA_LEFT,
        )

        # EMIS number style (red color)
        self.emis_style = ParagraphStyle(
            "EMISNumber",
            parent=self.styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#d32f2f"),  # Red color
            fontName="Helvetica",
            leading=10,
            alignment=TA_LEFT,
        )

        # Footer style
        self.footer_style = ParagraphStyle(
            "Footer",
            parent=self.styles["Normal"],
            fontSize=7,
            textColor=colors.HexColor("#757575"),
            alignment=TA_CENTER,
            fontName="Helvetica",
        )

        # Subject name style (for grades table)
        self.subject_style = ParagraphStyle(
            "SubjectName",
            parent=self.styles["Normal"],
            fontSize=8,  # Match the increased font size request
            textColor=colors.black,
            fontName="Helvetica",
            alignment=TA_LEFT,
            leading=9,
        )

    def _get_grade_paragraph(
        self, value: Union[float, str, None]
    ) -> Union[Paragraph, str]:
        """Get paragraph with appropriate color coding for grade"""
        if value is None or value == "":
            return ""

        try:
            float_val = float(value)
            text_val = f"{float_val:.1f}"

            if float_val >= 90:
                style = self.grade_style_blue
            elif float_val >= 70:
                style = self.grade_style_green
            else:
                style = self.grade_style_red

            return Paragraph(text_val, style)
        except (ValueError, TypeError):
            return str(value)

    def _get_school_logo(self) -> Optional[RLImage]:
        """Deprecated: Use shared get_school_logo from pdf_components instead"""
        from common.services.pdf_components import get_school_logo
        return get_school_logo(self.school, width=1.0 * inch, height=1.0 * inch)

    def _get_marking_periods_data(self) -> List[Dict]:
        """
        Get all marking periods organized by semester.
        Optimized query with select_related.
        """
        marking_periods = (
            MarkingPeriod.objects.filter(
                semester__academic_year=self.academic_year, active=True
            )
            .select_related("semester")
            .order_by("semester__start_date", "start_date")
        )

        # Organize by semester
        semesters_dict = {}
        for mp in marking_periods:
            semester_id = mp.semester.id
            if semester_id not in semesters_dict:
                semesters_dict[semester_id] = {
                    "semester": mp.semester,
                    "marking_periods": [],
                }
            semesters_dict[semester_id]["marking_periods"].append(mp)

        # Convert to list maintaining order
        result = []
        for semester_id in sorted(
            semesters_dict.keys(),
            key=lambda x: semesters_dict[x]["semester"].start_date,
        ):
            result.append(semesters_dict[semester_id])

        return result

    def _get_gradebooks_data(self) -> List[GradeBook]:
        """
        Get all gradebooks for the student's section and academic year.
        Optimized with select_related.
        """
        return list(
            GradeBook.objects.filter(
                section=self.enrollment.section,
                academic_year=self.academic_year,
                active=True,
            )
            .select_related(
                "subject", "section", "academic_year", "section_subject__subject"
            )
            .order_by("subject__name")
        )

    def _get_subject_grades(
        self, gradebook: GradeBook, marking_periods_data: List[Dict]
    ) -> Dict:
        """
        Get grades for a subject across all marking periods.
        Optimized to minimize database queries.
        """
        subject_data = {
            "subject_name": gradebook.subject.name,
            "marking_periods": {},
            "semester_averages": {},
            "final_average": None,
        }

        # Get all marking periods in a flat list for efficient querying
        all_mps = []
        for sem_data in marking_periods_data:
            for mp in sem_data["marking_periods"]:
                all_mps.append(mp)

        # Calculate percentage for each marking period
        mp_percentages = {}
        for mp in all_mps:
            percentage = calculate_marking_period_percentage(
                gradebook, self.student, mp, status="approved"
            )
            if percentage is not None:
                mp_percentages[mp.id] = float(percentage)
                subject_data["marking_periods"][mp.id] = {
                    "percentage": float(percentage),
                    "letter": get_letter_grade(float(percentage), self.school),
                }

        # Calculate semester averages (including exam periods)
        for sem_data in marking_periods_data:
            semester = sem_data["semester"]
            semester_mps = sem_data["marking_periods"]

            # Get percentages for ALL marking periods in this semester (including exams)
            sem_percentages = [
                mp_percentages.get(mp.id)
                for mp in semester_mps
                if mp.id in mp_percentages and mp_percentages.get(mp.id) is not None
            ]

            should_calculate_sem_avg = False
            if self.cumulative_average_calculation:
                # If cumulative is True, calculate if ANY grades exist
                if sem_percentages:
                    should_calculate_sem_avg = True
            else:
                # If cumulative is False, calculate only if ALL marking periods have grades
                # Check if we have grades for ALL marking periods in this semester
                all_mps_have_grades = all(
                    mp.id in mp_percentages and mp_percentages.get(mp.id) is not None
                    for mp in semester_mps
                )
                if all_mps_have_grades:
                    should_calculate_sem_avg = True

            if should_calculate_sem_avg:
                sem_avg = sum(sem_percentages) / len(sem_percentages)
                subject_data["semester_averages"][semester.id] = round(sem_avg, 1)

        # Calculate final average
        if self.cumulative_average_calculation:
            # Functionality the way it is: average of all marking period percentages
            if mp_percentages:
                all_percentages = list(mp_percentages.values())
                subject_data["final_average"] = round(
                    sum(all_percentages) / len(all_percentages), 1
                )
        else:
            # Determine if semester 1 and 2 averages are available
            # We check if we have averages for ALL semesters in the academic year
            # (Assuming academic year structure matches marking_periods_data semesters)
            all_semesters_have_avg = True
            sem_averages = []

            for sem_data in marking_periods_data:
                semester = sem_data["semester"]
                if semester.id in subject_data["semester_averages"]:
                    sem_averages.append(subject_data["semester_averages"][semester.id])
                else:
                    all_semesters_have_avg = False
                    break

            if all_semesters_have_avg and sem_averages:
                # Average of semester averages
                subject_data["final_average"] = round(
                    sum(sem_averages) / len(sem_averages), 1
                )

        return subject_data

    def _build_header(self, story: List) -> None:
        """Build the header section with logo and school info using shared component"""
        title_text = f"Student Report Card for {self.academic_year.name}"
        
        build_pdf_header(
            story=story,
            school=self.school,
            school_name_style=self.school_name_style,
            contact_style=self.contact_style,
            title_text=title_text,
            title_style=self.title_style,
            show_statement_date=False,
        )

    def _build_student_info(
        self, story: List, subjects_count: int, overall_avg: float
    ) -> None:
        """
        Build student information section without text wrapping.
        Uses a table layout with proper column widths to prevent wrapping.
        """
        # Truncate long values to prevent wrapping
        student_name = self.student.get_full_name()
        if len(student_name) > 30:
            student_name = student_name[:27] + "..."

        grade_text = (
            f"{self.enrollment.grade_level.name} - {self.enrollment.section.name}"
        )
        if len(grade_text) > 25:
            grade_text = grade_text[:22] + "..."

        # Create student info table with two columns (4 columns total: label, value, label, value)
        student_info_data = [
            [
                Paragraph("<b>Student Name:</b>", self.label_style),
                Paragraph(student_name, self.value_style),
                Paragraph("<b>Student ID:</b>", self.label_style),
                Paragraph(self.student.id_number, self.value_style),
            ],
            [
                Paragraph("<b>Grade:</b>", self.label_style),
                Paragraph(grade_text, self.value_style),
                Paragraph("<b>Academic Year:</b>", self.label_style),
                Paragraph(self.academic_year.name, self.value_style),
            ],
            [
                Paragraph("<b>Subjects:</b>", self.label_style),
                Paragraph(str(subjects_count), self.value_style),
                Paragraph("<b>Overall Average:</b>", self.label_style),
                Paragraph(f"{overall_avg:.1f}%", self.value_style),
            ],
        ]

        # Calculate column widths to prevent wrapping
        # Total width: 7 inches (letter size - margins)
        # Distribute: 1.3" (label) + 2.7" (value) + 1.3" (label) + 1.7" (value)
        student_info_table = Table(
            student_info_data,
            colWidths=[1.3 * inch, 2.7 * inch, 1.3 * inch, 1.7 * inch],
            hAlign="LEFT",
        )
        student_info_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
                    ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f5f5f5")),
                    # Prevent text wrapping
                    ("WORDWRAP", (0, 0), (-1, -1), False),
                ]
            )
        )

        story.append(student_info_table)
        story.append(Spacer(1, 0.15 * inch))

    def _build_grades_table(
        self, story: List, subjects_data: List[Dict], marking_periods_data: List[Dict]
    ) -> None:
        """
        Build the main grades table with all subjects and marking periods.
        Structure matches report card: Pd 1, Pd 2, Pd 3, Sem Exam 1, Sem 1 Ave, Pd 4, Pd 5, Pd 6, Sem Exam 2, Sem 2 Ave, Final Ave
        """
        # Build table headers matching the report card structure
        headers = ["Subjects"]

        # Track indices of average columns for styling
        # Start at 1 because column 0 is "Subjects"
        current_col_idx = 1
        sem_avg_col_indices = []
        final_avg_col_idx = None

        # Track column mapping for ranking
        # index -> {'type': 'mp'/'semester'/'final', 'id': ...}
        col_mapping = {}

        # Process each semester
        for sem_idx, sem_data in enumerate(marking_periods_data, 1):
            semester = sem_data["semester"]
            mps = sem_data["marking_periods"]

            # Separate regular marking periods from exam periods
            regular_mps = []
            exam_mp = None

            for mp in mps:
                if "exam" in mp.name.lower():
                    exam_mp = mp
                else:
                    regular_mps.append(mp)

            # Add regular marking periods (Pd 1, Pd 2, Pd 3, etc.)
            for mp in sorted(regular_mps, key=lambda x: x.start_date):
                headers.append(mp.short_name or mp.name[:10])
                col_mapping[current_col_idx] = {"type": "mp", "id": mp.id}
                current_col_idx += 1

            # Add semester exam if it exists
            if exam_mp:
                headers.append(exam_mp.short_name or "Sem Exam")
                col_mapping[current_col_idx] = {"type": "mp", "id": exam_mp.id}
                current_col_idx += 1

            # Add semester average column
            headers.append(f"Sem {sem_idx} Ave")
            col_mapping[current_col_idx] = {"type": "semester", "id": semester.id}
            sem_avg_col_indices.append(current_col_idx)
            current_col_idx += 1

        # Add final average column
        headers.append("Final Ave")
        col_mapping[current_col_idx] = {"type": "final"}
        final_avg_col_idx = current_col_idx

        # Build table data
        table_data = [headers]

        # Add subject rows
        for subject_data in subjects_data:
            # Store subject name as Paragraph to allow wrapping
            row = [Paragraph(subject_data["subject_name"], self.subject_style)]

            # Process each semester
            for sem_data in marking_periods_data:
                semester = sem_data["semester"]
                mps = sem_data["marking_periods"]

                # Separate regular marking periods from exam
                regular_mps = []
                exam_mp = None

                for mp in mps:
                    if "exam" in mp.name.lower():
                        exam_mp = mp
                    else:
                        regular_mps.append(mp)

                # Add regular marking period grades (in order)
                for mp in sorted(regular_mps, key=lambda x: x.start_date):
                    if mp.id in subject_data["marking_periods"]:
                        grade_info = subject_data["marking_periods"][mp.id]
                        row.append(self._get_grade_paragraph(grade_info["percentage"]))
                    else:
                        row.append("")

                # Add semester exam grade if exists
                if exam_mp:
                    if exam_mp.id in subject_data["marking_periods"]:
                        grade_info = subject_data["marking_periods"][exam_mp.id]
                        row.append(self._get_grade_paragraph(grade_info["percentage"]))
                    else:
                        row.append("")

                # Add semester average
                if semester.id in subject_data["semester_averages"]:
                    row.append(
                        self._get_grade_paragraph(
                            subject_data["semester_averages"][semester.id]
                        )
                    )
                else:
                    row.append("")

            # Add final average
            if subject_data["final_average"] is not None:
                row.append(self._get_grade_paragraph(subject_data["final_average"]))
            else:
                row.append("")

            table_data.append(row)

        # Add average row at bottom
        avg_row = ["Average"]
        rank_row = ["Rank"]

        # Calculate averages for each column
        for col_idx in range(1, len(headers)):
            column_values = []
            for row_idx in range(1, len(table_data)):  # Skip header row
                cell_value = table_data[row_idx][col_idx]
                # Handle both string and Paragraph objects
                if isinstance(cell_value, Paragraph):
                    # Extract text from Paragraph - get the plain text content
                    # Paragraph stores text in fragments, we need to extract it
                    try:
                        # Try to get text from the paragraph's fragments
                        cell_text = ""
                        if hasattr(cell_value, "frags"):
                            for frag in cell_value.frags:
                                if hasattr(frag, "text"):
                                    cell_text += frag.text
                        # Fallback: convert to string and extract numbers
                        if not cell_text:
                            cell_text = str(cell_value)
                            # Extract just the number part (e.g., "66.3" from Paragraph)
                            import re

                            match = re.search(r"(\d+\.?\d*)", cell_text)
                            if match:
                                cell_text = match.group(1)
                    except:
                        cell_text = ""
                else:
                    cell_text = str(cell_value) if cell_value else ""

                if cell_text and cell_text.strip():
                    try:
                        column_values.append(float(cell_text))
                    except ValueError:
                        pass

            if column_values:
                avg = sum(column_values) / len(column_values)
                avg_row.append(self._get_grade_paragraph(avg))
            else:
                avg_row.append("")

        # Calculate Rank for this column using optimized batch fetch
        # Fetch all ranks once
        all_ranks = RankingService.get_report_card_rankings(
            student_id=self.student.id,
            academic_year_id=self.academic_year.id,
            section_id=self.enrollment.section.id,
        )

        # Iterate again for rank row to ensure alignment
        for col_idx in range(1, len(headers)):
            rank_text = ""

            # Check if there is an average grade for this column first
            has_grade = False
            if col_idx < len(avg_row):
                val = avg_row[col_idx]
                if val != "":
                    has_grade = True

            col_type_info = col_mapping.get(col_idx)

            if has_grade and col_type_info:
                rank_info = None
                if col_type_info["type"] == "mp":
                    rank_info = all_ranks.get(f"mp_{col_type_info['id']}")
                elif col_type_info["type"] == "semester":
                    rank_info = all_ranks.get(f"semester_{col_type_info['id']}")
                elif col_type_info["type"] == "final":
                    rank_info = all_ranks.get("final")

                if rank_info:
                    rank_text = rank_info["label"]  # "Rank/Total"

            # Use grade style for rank text (bold)
            if rank_text:
                rank_row.append(Paragraph(rank_text, self.rank_style))
            else:
                rank_row.append("")

        table_data.append(avg_row)
        table_data.append(rank_row)

        # Create table with appropriate column widths for landscape
        # Landscape letter size: 11 x 8.5 inches
        # Available width: ~10 inches (with margins)
        # First column (Subjects) wider, others narrower
        col_widths = [1.5 * inch]  # Subjects column
        # Calculate width for other columns (distribute remaining space evenly)
        remaining_width = 8.5 * inch  # More space in landscape
        num_cols = len(headers) - 1
        if num_cols > 0:
            # Make grade columns narrower for better fit
            col_width = remaining_width / num_cols
            col_widths.extend([col_width] * num_cols)
        else:
            col_widths.append(remaining_width)

        grades_table = Table(table_data, colWidths=col_widths, repeatRows=1)

        # Apply table styling
        table_styles = [
            # Header row - light gray background
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
            # Data rows (rows 1 to -3)
            ("FONTNAME", (0, 1), (-1, -3), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -3), 7),
            ("TOPPADDING", (0, 1), (-1, -3), 3),
            ("BOTTOMPADDING", (0, 1), (-1, -3), 3),
            # Subject column (column 0) larger font
            ("FONTSIZE", (0, 1), (0, -3), 8),
            # Average and Rank rows (last 2 rows)
            ("BACKGROUND", (0, -2), (-1, -1), colors.HexColor("#eeeeee")),
            ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, -2), (-1, -1), 7),
            # Larger font for "Average" and "Rank" labels (col 0)
            ("FONTSIZE", (0, -2), (0, -1), 8),
            # Grid
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdbdbd")),
            # Alternating row colors for data rows
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -3),
                [colors.white, colors.HexColor("#fafafa")],
            ),
            # Left align subjects column
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("LEFTPADDING", (0, 0), (0, -1), 6),
        ]

        # Add styling for semester average columns (gray background)
        for col_idx in sem_avg_col_indices:
            # Apply to all data rows (1 to end)
            table_styles.append(
                (
                    "BACKGROUND",
                    (col_idx, 1),
                    (col_idx, -1),
                    colors.HexColor("#eeeeee"),
                )
            )
            # Make text bold
            table_styles.append(
                ("FONTNAME", (col_idx, 1), (col_idx, -1), "Helvetica-Bold")
            )

        # Add styling for final average column (light blue background)
        if final_avg_col_idx:
            table_styles.append(
                (
                    "BACKGROUND",
                    (final_avg_col_idx, 1),
                    (final_avg_col_idx, -1),
                    colors.HexColor("#e3f2fd"),
                )
            )
            table_styles.append(
                (
                    "FONTNAME",
                    (final_avg_col_idx, 1),
                    (final_avg_col_idx, -1),
                    "Helvetica-Bold",
                )
            )

        grades_table.setStyle(TableStyle(table_styles))

        story.append(KeepTogether(grades_table))
        story.append(Spacer(1, 0.1 * inch))

    def _build_footer(self, story: List) -> None:
        """Build footer with system information"""
        # Automatically get timezone from settings
        timezone_string = getattr(settings, "TIME_ZONE", "UTC")

        # Fallback to America/Chicago if settings is default UTC (common issue)
        if timezone_string == "UTC":
            timezone_string = "America/Chicago"

        try:
            user_tz = ZoneInfo(timezone_string)
        except Exception:
            user_tz = ZoneInfo("America/Chicago")

        now_local = datetime.now(user_tz)

        footer_text = (
            f"EzySchool • Easy School Management System • www.ezyschool.net<br/>"
            f"Generated: {now_local.strftime('%b %d, %Y %I:%M %p')}"
        )
        footer = Paragraph(footer_text, self.footer_style)
        story.append(footer)

    def generate(self) -> BytesIO:
        """
        Generate the complete PDF report.
        Optimized with efficient queries and caching.
        Uses landscape orientation to fit all columns.
        """
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),  # Landscape orientation
            topMargin=0.3 * inch,
            bottomMargin=0.3 * inch,
            leftMargin=0.4 * inch,
            rightMargin=0.4 * inch,
        )
        story = []

        # Build header
        self._build_header(story)

        # Data retrieval with caching
        # 1. Get latest grade update timestamp for invalidation
        # This ensures we always show fresh data if grades change, but use cache otherwise
        latest_grade_ts = Grade.objects.filter(
            student=self.student,
            assessment__gradebook__academic_year=self.academic_year,
        ).aggregate(Max("updated_at"))["updated_at__max"]

        ts_str = latest_grade_ts.isoformat() if latest_grade_ts else "no_grades"
        cache_key = (
            f"student_report_data:{self.student.id}:{self.academic_year.id}:{ts_str}"
        )

        cached_data = cache.get(cache_key)

        if cached_data:
            subjects_data, marking_periods_data, overall_avg = cached_data
        else:
            # Get data efficiently
            marking_periods_data = self._get_marking_periods_data()
            gradebooks = self._get_gradebooks_data()

            # Get subject grades data
            subjects_data = []
            for gradebook in gradebooks:
                subject_data = self._get_subject_grades(gradebook, marking_periods_data)
                subjects_data.append(subject_data)

            # Calculate overall average
            overall_avg_data = calculate_student_overall_average(
                self.student,
                self.academic_year,
                gradebooks=gradebooks,
                status="approved",
            )
            overall_avg = overall_avg_data.get("final_average", 0) or 0

            # Cache for 1 hour (invalidation handled by timestamp in key)
            cache.set(
                cache_key, (subjects_data, marking_periods_data, overall_avg), 3600
            )

        # Build student info section
        self._build_student_info(story, len(subjects_data), overall_avg)

        # Build grades table
        self._build_grades_table(story, subjects_data, marking_periods_data)

        # Build footer
        self._build_footer(story)

        # Build PDF
        doc.build(story)
        buffer.seek(0)

        return buffer


def generate_student_report_card_pdf(
    student: Student,
    academic_year: AcademicYear,
    enrollment: Optional[Enrollment] = None,
) -> HttpResponse:
    """
    Generate and return HTTP response with student report card PDF.

    Args:
        student: Student instance
        academic_year: AcademicYear instance
        enrollment: Optional Enrollment instance (will be fetched if not provided)

    Returns:
        HttpResponse with PDF file
    """
    # Get enrollment if not provided
    if enrollment is None:
        try:
            enrollment = Enrollment.objects.get(
                student=student, academic_year=academic_year
            )
        except Enrollment.DoesNotExist:
            return HttpResponse(
                "Student is not enrolled in this academic year.", status=404
            )

    # Generate PDF
    pdf_generator = StudentReportCardPDF(student, academic_year, enrollment)
    pdf_buffer = pdf_generator.generate()

    # Create HTTP response
    response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="report_card_{student.id_number}_{academic_year.name.replace(" ", "_")}.pdf"'
    )

    return response

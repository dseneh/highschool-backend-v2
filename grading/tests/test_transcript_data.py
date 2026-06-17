"""Tests for official transcript data aggregation."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from grading.services.transcript_data import (
    TranscriptAcademicRow,
    TranscriptDataService,
    TranscriptYearBlock,
    _format_grade_display,
    _historical_subject_final,
    _parse_year_sort_key,
    _subject_transcript_percentage,
)


class TranscriptDataHelpersTests(SimpleTestCase):
    def test_parse_year_sort_key(self):
        self.assertEqual(_parse_year_sort_key("2023-2024"), 2023)
        self.assertEqual(_parse_year_sort_key("Grade 10"), 0)

    def test_format_grade_display(self):
        self.assertIn("87.5%", _format_grade_display(87.5, "B+"))
        self.assertEqual(_format_grade_display(None, "A"), "A")
        self.assertEqual(_format_grade_display(None, None), "-")


class TranscriptGroupingTests(SimpleTestCase):
    @patch("grading.services.transcript_data.get_letter_grade", return_value="B")
    def test_group_into_year_blocks(self, _mock_letter):
        rows = [
            TranscriptAcademicRow(
                institution_name="Test School",
                academic_year_name="2022-2023",
                grade_level_name="Grade 9",
                marking_period="Final",
                marking_period_order=0,
                subject_code="ENG101",
                subject_name="English I",
                grade_display="A (92.0%)",
                percentage=92.0,
                sort_end_date=date(2023, 6, 1),
            ),
            TranscriptAcademicRow(
                institution_name="Test School",
                academic_year_name="2022-2023",
                grade_level_name="Grade 9",
                marking_period="Final",
                marking_period_order=0,
                subject_code="MATH101",
                subject_name="Algebra I",
                grade_display="B (88.0%)",
                percentage=88.0,
                sort_end_date=date(2023, 6, 1),
            ),
            TranscriptAcademicRow(
                institution_name="Prior School",
                academic_year_name="2023-2024",
                grade_level_name="Grade 10",
                marking_period="Final",
                marking_period_order=0,
                subject_code="—",
                subject_name="Algebra I",
                grade_display="B (85.0%)",
                percentage=85.0,
                sort_end_date=date(2024, 6, 1),
                sort_grade_level=10,
            ),
        ]

        blocks = TranscriptDataService._group_into_year_blocks(rows)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(len(blocks[0].rows), 2)
        self.assertEqual(len(blocks[1].rows), 1)
        self.assertEqual(blocks[0].academic_year_name, "2022-2023")
        self.assertEqual(blocks[1].grade_level_name, "Grade 10")

        TranscriptDataService._attach_year_averages(blocks)
        self.assertEqual(blocks[0].year_average, 90.0)
        self.assertEqual(blocks[1].year_average, 85.0)

    def test_group_into_year_blocks_keeps_institutions_separate(self):
        rows = [
            TranscriptAcademicRow(
                institution_name="School A",
                academic_year_name="2022-2023",
                grade_level_name="Grade 9",
                marking_period="Final",
                marking_period_order=0,
                subject_code="ENG101",
                subject_name="English I",
                grade_display="A (92.0%)",
                percentage=92.0,
                sort_end_date=date(2023, 6, 1),
            ),
            TranscriptAcademicRow(
                institution_name="School B",
                academic_year_name="2022-2023",
                grade_level_name="Grade 9",
                marking_period="Final",
                marking_period_order=0,
                subject_code="ENG101",
                subject_name="English I",
                grade_display="B (88.0%)",
                percentage=88.0,
                sort_end_date=date(2023, 6, 1),
            ),
        ]

        blocks = TranscriptDataService._group_into_year_blocks(rows)
        self.assertEqual(len(blocks), 2)


class TranscriptPivotTests(SimpleTestCase):
    @patch("grading.services.transcript_data.get_letter_grade", return_value="B")
    def test_pivot_to_subject_rows_limits_years_and_fills_dashes(self, _mock_letter):
        blocks = [
            TranscriptYearBlock(
                institution_name="Test School",
                academic_year_name="2022-2023",
                grade_level_name="Grade 9",
                sort_end_date=date(2023, 6, 1),
                rows=[
                    TranscriptAcademicRow(
                        institution_name="Test School",
                        academic_year_name="2022-2023",
                        grade_level_name="Grade 9",
                        marking_period="Final",
                        marking_period_order=0,
                        subject_code="ENG",
                        subject_name="English",
                        grade_display="A (92.0%)",
                        percentage=92.0,
                        letter="A",
                    ),
                ],
            ),
            TranscriptYearBlock(
                institution_name="Test School",
                academic_year_name="2023-2024",
                grade_level_name="Grade 10",
                sort_end_date=date(2024, 6, 1),
                rows=[
                    TranscriptAcademicRow(
                        institution_name="Test School",
                        academic_year_name="2023-2024",
                        grade_level_name="Grade 10",
                        marking_period="Final",
                        marking_period_order=0,
                        subject_code="ENG",
                        subject_name="English",
                        grade_display="B (88.0%)",
                        percentage=88.0,
                        letter="B",
                    ),
                    TranscriptAcademicRow(
                        institution_name="Test School",
                        academic_year_name="2023-2024",
                        grade_level_name="Grade 10",
                        marking_period="Final",
                        marking_period_order=0,
                        subject_code="MATH",
                        subject_name="Algebra",
                        grade_display="A (90.0%)",
                        percentage=90.0,
                        letter="A",
                    ),
                ],
            ),
        ]

        year_columns, subject_rows = TranscriptDataService._pivot_to_subject_rows(
            blocks,
            max_years=3,
        )
        self.assertEqual(len(year_columns), 2)
        self.assertEqual([row.subject_name for row in subject_rows], ["Algebra", "English"])
        english = next(row for row in subject_rows if row.subject_code == "ENG")
        self.assertEqual(english.year_grades["2022-2023"][0], 92.0)
        self.assertEqual(english.year_grades["2023-2024"][0], 88.0)
        self.assertEqual(english.final_average, 90.0)


class TranscriptHistoricalFinalTests(SimpleTestCase):
    def test_historical_subject_final_prefers_full_year_record(self):
        records = [
            SimpleNamespace(
                marking_period_id="mp-1",
                final_percentage=Decimal("80"),
                final_letter="B-",
            ),
            SimpleNamespace(
                marking_period_id=None,
                final_percentage=Decimal("90"),
                final_letter="A-",
            ),
        ]
        pct, letter = _historical_subject_final(records)
        self.assertEqual(pct, 90.0)
        self.assertEqual(letter, "A-")

    @patch("grading.services.transcript_data.get_letter_grade", return_value="B")
    def test_historical_subject_final_averages_marking_periods(self, _mock_letter):
        records = [
            SimpleNamespace(
                marking_period_id="mp-1",
                final_percentage=Decimal("80"),
                final_letter="B-",
            ),
            SimpleNamespace(
                marking_period_id="mp-2",
                final_percentage=Decimal("90"),
                final_letter="A-",
            ),
        ]
        pct, letter = _historical_subject_final(records)
        self.assertEqual(pct, 85.0)
        self.assertEqual(letter, "B")


class TranscriptInSchoolPercentageTests(SimpleTestCase):
    def test_subject_transcript_percentage_uses_partial_for_current_year(self):
        gradebook = SimpleNamespace(
            final_percentage_for_student=lambda _student, status="approved": Decimal("88.5"),
        )
        pct = _subject_transcript_percentage(
            SimpleNamespace(),
            gradebook,
            [],
            allow_partial=True,
        )
        self.assertEqual(pct, 88.5)

    def test_subject_transcript_percentage_requires_complete_year_when_not_partial(self):
        gradebook = SimpleNamespace(
            final_percentage_for_student=lambda *_args, **_kwargs: Decimal("88.5"),
        )
        with patch(
            "grading.services.transcript_data._subject_final_percentage",
            return_value=None,
        ) as mock_final:
            pct = _subject_transcript_percentage(
                SimpleNamespace(),
                gradebook,
                [],
                allow_partial=False,
            )
        mock_final.assert_called_once()
        self.assertIsNone(pct)


class TranscriptHonorMatchTests(SimpleTestCase):
    def test_match_honor_category(self):
        categories = [
            SimpleNamespace(label="Principal's List", min_average=Decimal("95"), max_average=Decimal("100")),
            SimpleNamespace(label="Honor Roll", min_average=Decimal("90"), max_average=Decimal("94.99")),
        ]
        self.assertEqual(
            TranscriptDataService._match_honor_category(categories, 96.0),
            "Principal's List",
        )
        self.assertIsNone(TranscriptDataService._match_honor_category(categories, 80.0))


class TranscriptBuildTests(SimpleTestCase):
    @patch("students.services.student_status.compute_is_enrolled", return_value=False)
    @patch("grading.services.transcript_data.GradeLetter.objects")
    @patch("grading.services.transcript_data.HonorCategory.objects")
    @patch("grading.services.transcript_data.HistoricalGradeRecord.objects")
    @patch("grading.services.transcript_data.Enrollment.objects")
    @patch("grading.services.transcript_data.resolve_tenant_school")
    def test_build_with_no_enrollments(
        self,
        mock_resolve_school,
        mock_enrollment_qs,
        mock_prior_qs,
        mock_honor_qs,
        mock_grade_letter_qs,
        _mock_is_enrolled,
    ):
        mock_resolve_school.return_value = SimpleNamespace(
            name="Test School",
            phone="555-0100",
            website="https://school.test",
            email="office@school.test",
            emis_number="12345",
        )
        mock_enrollment_qs.filter.return_value.select_related.return_value.order_by.return_value = []
        mock_prior_qs.filter.return_value.select_related.return_value.order_by.return_value = []
        mock_honor_qs.all.return_value.order_by.return_value = []
        mock_grade_letter_qs.all.return_value.order_by.return_value = []

        student = SimpleNamespace(
            id="student-uuid",
            id_number="10001",
            school=None,
            grade_level=None,
            status="active",
            date_of_graduation=None,
            entry_date=None,
            photo=None,
            get_full_name=lambda: "Jane Doe",
            date_of_birth=None,
        )

        payload = TranscriptDataService.build(student)

        self.assertEqual(payload.student_full_name, "Jane Doe")
        self.assertEqual(payload.student_id_number, "10001")
        self.assertTrue(payload.transcript_id.startswith("TRN-"))
        self.assertEqual(payload.year_blocks, [])
        self.assertIsNone(payload.cumulative_average)

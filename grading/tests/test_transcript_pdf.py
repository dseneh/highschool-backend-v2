"""Tests for official transcript PDF rendering and background worker."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from grading.services.transcript_data import (
    TranscriptDataService,
    TranscriptPayload,
    TranscriptYearBlock,
    TranscriptYearColumn,
    TranscriptSubjectRow,
)
from grading.services.transcript_pdf import OfficialTranscriptPDF, build_official_transcript_pdf_bytes
from grading.tasks.transcript_worker import start_official_transcript_background_task
from reports.tasks import TaskManager


def _sample_payload() -> TranscriptPayload:
    return TranscriptPayload(
        school_name="Riverdale High School",
        school_address="123 Main St, Riverdale",
        school_phone="555-0100",
        school_website="https://riverdale.test",
        school_email="office@riverdale.test",
        emis_number="052345",
        transcript_id="TRN-2026-10001",
        date_issued="June 8, 2026",
        student_full_name="James Alexander Martinez",
        student_id_number="10001",
        date_of_birth="March 15, 2008",
        grade_level="Grade 11",
        graduation_year="2026",
        date_enrolled="September 1, 2021",
        photo_path=None,
        cumulative_average=88.5,
        class_rank="18 of 156",
        percentile_rank="88th Percentile",
        total_subjects=18,
        graduation_status="On Track",
        current_section="Section A",
        year_blocks=[
            TranscriptYearBlock(
                institution_name="Riverdale High School",
                academic_year_name="2025-2026",
                grade_level_name="Grade 11",
                rows=[],
                year_average=None,
            )
        ],
        grade_scale=[],
        honors=["Honor Roll - 2025-2026"],
        signatory_name="Dr. Amanda Peters",
        signatory_title="Principal",
        secondary_signatory_name="Mrs. Grace Cole",
        secondary_signatory_title="Registrar",
        disclaimer=TranscriptDataService.DISCLAIMER,
        year_columns=[
            TranscriptYearColumn(
                academic_year_name="2025-2026",
                grade_level_name="Grade 11",
            )
        ],
        subject_rows=[
            TranscriptSubjectRow(
                subject_code="MATH",
                subject_name="Mathematics",
                year_grades={"2025-2026": (88.5, "B+")},
                final_average=88.5,
                final_average_letter="B+",
            )
        ],
    )


class OfficialTranscriptPDFTests(SimpleTestCase):
    def test_generate_returns_pdf_bytes(self):
        payload = _sample_payload()
        pdf = OfficialTranscriptPDF(payload, school=SimpleNamespace(name="Riverdale High School"))
        buffer = pdf.generate()
        content = buffer.getvalue()
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertGreater(len(content), 500)


class TranscriptWorkerTests(SimpleTestCase):
    @patch("grading.tasks.transcript_worker.build_official_transcript_pdf_bytes")
    @patch("grading.tasks.transcript_worker.get_student_by_identifier")
    def test_background_task_caches_pdf_and_completes(
        self,
        mock_get_student,
        mock_build_pdf,
    ):
        mock_build_pdf.return_value = b"%PDF-1.4 test transcript"
        mock_get_student.return_value = SimpleNamespace(
            id="student-uuid",
            id_number="10001",
        )

        task_id = TaskManager.create_task(
            task_type="official_transcript_pdf",
            query_params={"student_id": "student-uuid", "cache_key": "cache-1"},
            user_id=1,
            estimated_count=1,
        )

        start_official_transcript_background_task(
            task_id,
            student_id="student-uuid",
            cache_key="cache-1",
        )

        import time

        for _ in range(30):
            task = TaskManager.get_task(task_id)
            if task and task.get("status") in {"completed", "failed"}:
                break
            time.sleep(0.1)

        task = TaskManager.get_task(task_id)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["progress"], 100)

        cached = TaskManager.get_cached_result("cache-1")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["kind"], "file")
        self.assertEqual(cached["content"], b"%PDF-1.4 test transcript")


class BuildOfficialTranscriptBytesTests(SimpleTestCase):
    @patch("grading.services.transcript_pdf.OfficialTranscriptPDF.generate")
    @patch("grading.services.transcript_pdf.TranscriptDataService.build")
    @patch("grading.services.transcript_pdf.resolve_tenant_school")
    def test_build_official_transcript_pdf_bytes(
        self,
        mock_resolve_school,
        mock_build_payload,
        mock_generate,
    ):
        mock_build_payload.return_value = _sample_payload()
        mock_resolve_school.return_value = SimpleNamespace(name="Test School")
        mock_generate.return_value = BytesIO(b"%PDF-1.4 generated")

        student = SimpleNamespace(id="student-uuid", school=None)
        content = build_official_transcript_pdf_bytes(student)

        self.assertEqual(content, b"%PDF-1.4 generated")
        mock_build_payload.assert_called_once_with(student)

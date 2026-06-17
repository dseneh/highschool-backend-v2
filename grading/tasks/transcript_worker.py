"""Background worker for official transcript PDF generation."""

from __future__ import annotations

import logging
import threading

from django.db import close_old_connections, connection
from django_tenants.utils import schema_context

from grading.services.transcript_pdf import build_official_transcript_pdf_bytes
from reports.settings import get_reports_setting
from reports.tasks import TaskManager
from students.services.student_lookup import get_student_by_identifier

logger = logging.getLogger(__name__)


def start_official_transcript_background_task(
    task_id: str,
    *,
    student_id: str,
    cache_key: str,
    schema_name: str | None = None,
) -> None:
    """Generate transcript PDF in a background thread."""

    tenant_schema = schema_name or getattr(connection, "schema_name", None)

    def background_work() -> None:
        close_old_connections()
        if not tenant_schema:
            TaskManager.update_task(
                task_id,
                status="failed",
                error="Transcript task is missing tenant schema context.",
            )
            return

        try:
            with schema_context(tenant_schema):
                TaskManager.update_task(task_id, status="processing", progress=10)

                student = get_student_by_identifier(student_id)
                TaskManager.update_task(task_id, progress=40)

                pdf_bytes = build_official_transcript_pdf_bytes(student)
                TaskManager.update_task(task_id, progress=90)

                payload = {
                    "kind": "file",
                    "content_type": "application/pdf",
                    "filename": f"Official_Transcript_{student.id_number}.pdf",
                    "content": pdf_bytes,
                }

                task_timeout = int(get_reports_setting("TASK_CACHE_TIMEOUT", 3600) or 3600)
                TaskManager.cache_result(cache_key, payload, timeout=task_timeout)

                TaskManager.update_task(
                    task_id,
                    status="completed",
                    progress=100,
                    total_processed=1,
                    result_url=f"/api/v1/reports/download/{task_id}/",
                )
        except Exception as exc:
            logger.exception("Official transcript generation failed for task %s", task_id)
            TaskManager.update_task(
                task_id,
                status="failed",
                error=str(exc),
            )

    thread = threading.Thread(target=background_work)
    thread.daemon = True
    thread.start()

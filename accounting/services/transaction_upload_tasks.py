"""Background task management for large cash-transaction template uploads."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import pandas as pd
from django.core.cache import cache


class TransactionUploadTaskManager:
    CACHE_PREFIX = "accounting_tx_upload_task"
    BACKGROUND_ROW_THRESHOLD = 200

    @classmethod
    def should_use_background(cls, row_count: int) -> bool:
        return row_count > cls.BACKGROUND_ROW_THRESHOLD

    @classmethod
    def create_task(
        cls,
        *,
        template_type: str,
        row_count: int,
        user_id: int | None,
        file_name: str,
        schema_name: str | None = None,
    ) -> str:
        if schema_name is None:
            from django.db import connection

            schema_name = connection.schema_name

        task_id = str(uuid.uuid4())
        task_data = {
            "id": task_id,
            "type": "transaction_upload",
            "status": "pending",
            "progress": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "schema_name": schema_name,
            "template_type": template_type,
            "file_name": file_name,
            "estimated_count": row_count,
            "total_processed": 0,
            "created": 0,
            "updated": 0,
            "total_errors": 0,
            "errors": [],
            "error": None,
            "result": None,
        }
        cache.set(f"{cls.CACHE_PREFIX}_{task_id}", task_data, timeout=7200)
        return task_id

    @classmethod
    def get_task(cls, task_id: str) -> dict[str, Any] | None:
        return cache.get(f"{cls.CACHE_PREFIX}_{task_id}")

    @classmethod
    def update_task(cls, task_id: str, **updates) -> bool:
        task_data = cls.get_task(task_id)
        if not task_data:
            return False
        task_data.update(updates)
        task_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        cache.set(f"{cls.CACHE_PREFIX}_{task_id}", task_data, timeout=7200)
        return True

    @classmethod
    def is_cancelled(cls, task_id: str) -> bool:
        task_data = cls.get_task(task_id)
        return bool(task_data and task_data.get("status") == "cancelled")


class TransactionUploadBackgroundProcessor:
    @staticmethod
    def start(
        task_id: str,
        df: pd.DataFrame,
        *,
        template_type: str,
        bank_account_id: str | None,
        gl_account_override: str | None,
        status_override: str | None,
        replace_by_ref_number: bool,
    ) -> None:
        from accounting.services.transaction_upload import execute_transaction_upload

        def background_work() -> None:
            from django.db import close_old_connections
            from django_tenants.utils import schema_context

            close_old_connections()
            task_data = TransactionUploadTaskManager.get_task(task_id)
            if not task_data:
                return

            schema_name = task_data.get("schema_name")
            if not schema_name:
                TransactionUploadTaskManager.update_task(
                    task_id,
                    status="failed",
                    error="Upload task is missing tenant schema context.",
                )
                return

            try:
                with schema_context(schema_name):
                    TransactionUploadTaskManager.update_task(
                        task_id, status="processing", progress=5
                    )

                    def on_progress(processed: int, total: int) -> None:
                        if TransactionUploadTaskManager.is_cancelled(task_id):
                            return
                        progress = 5 + int((processed / max(total, 1)) * 90)
                        TransactionUploadTaskManager.update_task(
                            task_id,
                            progress=min(progress, 95),
                            total_processed=processed,
                        )

                    result = execute_transaction_upload(
                        df,
                        template_type=template_type,
                        bank_account_id=bank_account_id,
                        gl_account_override=gl_account_override,
                        status_override=status_override,
                        replace_by_ref_number=replace_by_ref_number,
                        progress_callback=on_progress,
                        cancel_check=lambda: TransactionUploadTaskManager.is_cancelled(
                            task_id
                        ),
                    )

                    if TransactionUploadTaskManager.is_cancelled(task_id):
                        TransactionUploadTaskManager.update_task(
                            task_id,
                            result=result,
                            total_errors=len(result.get("errors") or []),
                            errors=(result.get("errors") or [])[:20],
                        )
                        return

                    TransactionUploadTaskManager.update_task(
                        task_id,
                        status="completed",
                        progress=100,
                        result=result,
                        total_processed=result.get("total_rows") or len(df),
                        created=result.get("created") or 0,
                        updated=result.get("updated") or 0,
                        total_errors=len(result.get("errors") or []),
                        errors=(result.get("errors") or [])[:20],
                    )
            except Exception as exc:
                TransactionUploadTaskManager.update_task(
                    task_id,
                    status="failed",
                    error=str(exc),
                )

        thread = threading.Thread(target=background_work, daemon=True)
        thread.start()

"""Background task management for bulk post-all cash transactions."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from django.core.cache import cache


class PostAllTaskManager:
    CACHE_PREFIX = "accounting_post_all_task"
    BACKGROUND_THRESHOLD = 50

    @classmethod
    def should_use_background(cls, transaction_count: int) -> bool:
        return transaction_count > cls.BACKGROUND_THRESHOLD

    @classmethod
    def create_task(
        cls,
        *,
        estimated_count: int,
        user_id: int | None,
        apply_filters: bool,
        filter_params: dict[str, str],
        schema_name: str | None = None,
    ) -> str:
        if schema_name is None:
            from django.db import connection

            schema_name = connection.schema_name

        task_id = str(uuid.uuid4())
        task_data = {
            "id": task_id,
            "type": "post_all_cash_transactions",
            "status": "pending",
            "progress": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "schema_name": schema_name,
            "apply_filters": apply_filters,
            "filter_params": filter_params,
            "estimated_count": estimated_count,
            "total_processed": 0,
            "posted_count": 0,
            "skipped_count": 0,
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


class PostAllBackgroundProcessor:
    @staticmethod
    def start(task_id: str) -> None:
        from accounting.services.post_all import execute_post_all

        def background_work() -> None:
            from django.db import close_old_connections
            from django_tenants.utils import schema_context

            close_old_connections()
            task_data = PostAllTaskManager.get_task(task_id)
            if not task_data:
                return

            schema_name = task_data.get("schema_name")
            if not schema_name:
                PostAllTaskManager.update_task(
                    task_id,
                    status="failed",
                    error="Post-all task is missing tenant schema context.",
                )
                return

            try:
                with schema_context(schema_name):
                    PostAllTaskManager.update_task(
                        task_id, status="processing", progress=5
                    )

                    def on_progress(processed: int, total: int) -> None:
                        if PostAllTaskManager.is_cancelled(task_id):
                            return
                        progress = 5 + int((processed / max(total, 1)) * 90)
                        PostAllTaskManager.update_task(
                            task_id,
                            progress=min(progress, 95),
                            total_processed=processed,
                        )

                    result = execute_post_all(
                        user_id=task_data.get("user_id"),
                        apply_filters=bool(task_data.get("apply_filters", True)),
                        filter_params=task_data.get("filter_params") or {},
                        progress_callback=on_progress,
                        cancel_check=lambda: PostAllTaskManager.is_cancelled(task_id),
                    )

                    if PostAllTaskManager.is_cancelled(task_id):
                        PostAllTaskManager.update_task(
                            task_id,
                            result=result,
                            posted_count=result.get("posted_count") or 0,
                            skipped_count=result.get("skipped_count") or 0,
                            errors=(result.get("errors") or [])[:20],
                        )
                        return

                    PostAllTaskManager.update_task(
                        task_id,
                        status="completed",
                        progress=100,
                        result=result,
                        total_processed=(
                            (result.get("posted_count") or 0)
                            + (result.get("skipped_count") or 0)
                        ),
                        posted_count=result.get("posted_count") or 0,
                        skipped_count=result.get("skipped_count") or 0,
                        errors=(result.get("errors") or [])[:20],
                    )
            except Exception as exc:
                PostAllTaskManager.update_task(
                    task_id,
                    status="failed",
                    error=str(exc),
                )

        thread = threading.Thread(target=background_work, daemon=True)
        thread.start()

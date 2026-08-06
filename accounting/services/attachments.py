"""Attachment security and path helpers for accounting uploads."""

from __future__ import annotations

import re
from uuid import uuid4

from django.conf import settings


def sanitize_filename(filename: str) -> str:
    """Keep attachment filenames storage-safe and deterministic."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", (filename or "").strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-.")
    return cleaned or "attachment"


def build_accounting_attachment_key(*, tenant_schema: str, record_type: str, record_id: str, filename: str) -> str:
    """
    Build an object key under the accounting attachment prefix.

    Final S3/R2 location in production (via TenantAwareS3Storage):
    tenants/<tenant_schema>/<ACCOUNTING_ATTACHMENT_UPLOAD_PREFIX>/<record_type>/<record_id>/<uuid>-<filename>
    """
    prefix = str(getattr(settings, "ACCOUNTING_ATTACHMENT_UPLOAD_PREFIX", "accounting/attachments")).strip("/")
    schema = (tenant_schema or "public").strip("/")
    safe_type = sanitize_filename(record_type)
    safe_record_id = sanitize_filename(record_id)
    safe_name = sanitize_filename(filename)
    return f"tenants/{schema}/{prefix}/{safe_type}/{safe_record_id}/{uuid4().hex}-{safe_name}"


def get_accounting_attachment_policy() -> dict[str, object]:
    """Expose current server-side attachment policy for validation endpoints."""
    return {
        "max_file_size_bytes": int(getattr(settings, "ACCOUNTING_ATTACHMENT_MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)),
        "allowed_mime_types": list(getattr(settings, "ACCOUNTING_ATTACHMENT_ALLOWED_MIME_TYPES", [])),
        "allowed_extensions": list(getattr(settings, "ACCOUNTING_ATTACHMENT_ALLOWED_EXTENSIONS", [])),
        "upload_prefix": str(getattr(settings, "ACCOUNTING_ATTACHMENT_UPLOAD_PREFIX", "accounting/attachments")),
    }

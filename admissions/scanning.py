from __future__ import annotations

import logging
import socket
import struct
from dataclasses import dataclass
from datetime import timedelta
from typing import BinaryIO

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ApplicationDocument

logger = logging.getLogger(__name__)

CLAMAV_ENGINE = "clamav"
STREAM_CHUNK_SIZE = 64 * 1024
MAX_RESPONSE_BYTES = 4096


class DocumentScanError(Exception):
    """A scan could not produce a trustworthy verdict."""


@dataclass(frozen=True)
class ScanVerdict:
    clean: bool
    threat_name: str = ""


class ClamAVScanner:
    """Minimal clamd INSTREAM client with no local file-path exposure."""

    def __init__(self, *, host: str, port: int, timeout: int):
        if not host:
            raise DocumentScanError("ClamAV host is not configured.")
        self.host = host
        self.port = port
        self.timeout = timeout

    def scan(self, stream: BinaryIO) -> ScanVerdict:
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            ) as connection:
                connection.sendall(b"zINSTREAM\0")
                while chunk := stream.read(STREAM_CHUNK_SIZE):
                    connection.sendall(struct.pack("!I", len(chunk)))
                    connection.sendall(chunk)
                connection.sendall(struct.pack("!I", 0))
                response = self._read_response(connection)
        except (OSError, TimeoutError) as exc:
            raise DocumentScanError("ClamAV is unavailable.") from exc

        message = response.rstrip("\0\r\n")
        if message.endswith(": OK"):
            return ScanVerdict(clean=True)
        if message.endswith(" FOUND") and ": " in message:
            threat = message.rsplit(": ", 1)[-1].removesuffix(" FOUND").strip()
            return ScanVerdict(clean=False, threat_name=threat or "unknown")
        raise DocumentScanError("ClamAV returned an invalid scan response.")

    @staticmethod
    def _read_response(connection: socket.socket) -> str:
        response = bytearray()
        while len(response) < MAX_RESPONSE_BYTES:
            part = connection.recv(min(1024, MAX_RESPONSE_BYTES - len(response)))
            if not part:
                break
            response.extend(part)
            if b"\0" in part or b"\n" in part:
                break
        if not response:
            raise DocumentScanError("ClamAV returned no scan response.")
        return response.decode("utf-8", errors="replace")


def configured_scanner() -> ClamAVScanner:
    return ClamAVScanner(
        host=settings.ADMISSIONS_DOCUMENT_SCAN_HOST,
        port=settings.ADMISSIONS_DOCUMENT_SCAN_PORT,
        timeout=settings.ADMISSIONS_DOCUMENT_SCAN_TIMEOUT,
    )


def reset_stale_document_scans() -> int:
    cutoff = timezone.now() - timedelta(
        seconds=settings.ADMISSIONS_DOCUMENT_SCAN_STALE_SECONDS
    )
    stale = ApplicationDocument.objects.filter(
        scan_status=ApplicationDocument.ScanStatus.SCANNING,
        scan_started_at__lt=cutoff,
    )
    now = timezone.now()
    failed = stale.filter(
        scan_attempts__gte=settings.ADMISSIONS_DOCUMENT_SCAN_MAX_ATTEMPTS
    ).update(
        scan_status=ApplicationDocument.ScanStatus.FAILED,
        scan_started_at=None,
        scan_completed_at=now,
        scan_engine=CLAMAV_ENGINE,
        scan_error="Scanner worker stopped before returning a verdict.",
        updated_at=now,
    )
    pending = stale.filter(
        scan_attempts__lt=settings.ADMISSIONS_DOCUMENT_SCAN_MAX_ATTEMPTS
    ).update(
        scan_status=ApplicationDocument.ScanStatus.PENDING,
        scan_started_at=None,
        scan_error="Scanner worker stopped before returning a verdict.",
        updated_at=now,
    )
    return failed + pending


def claim_pending_document_ids(*, batch_size: int) -> list[str]:
    """Atomically claim work so multiple workers cannot scan the same upload."""
    with transaction.atomic():
        documents = list(
            ApplicationDocument.objects.select_for_update(skip_locked=True)
            .filter(
                scan_status=ApplicationDocument.ScanStatus.PENDING,
                scan_attempts__lt=settings.ADMISSIONS_DOCUMENT_SCAN_MAX_ATTEMPTS,
            )
            .order_by("created_at")[:batch_size]
        )
        now = timezone.now()
        for document in documents:
            document.scan_status = ApplicationDocument.ScanStatus.SCANNING
            document.scan_started_at = now
            document.scan_attempts += 1
            document.scan_error = ""
            document.save(
                update_fields=[
                    "scan_status",
                    "scan_started_at",
                    "scan_attempts",
                    "scan_error",
                    "updated_at",
                ]
            )
    return [str(document.pk) for document in documents]


def scan_claimed_document(document_id: str, *, scanner=None) -> str:
    document = ApplicationDocument.objects.get(pk=document_id)
    if document.scan_status != ApplicationDocument.ScanStatus.SCANNING:
        return document.scan_status

    try:
        scanner = scanner or configured_scanner()
        document.file.open("rb")
        try:
            verdict = scanner.scan(document.file)
        finally:
            document.file.close()
    except Exception as exc:
        logger.warning(
            "Admissions document scan failed",
            extra={"document_id": str(document.pk), "attempt": document.scan_attempts},
            exc_info=True,
        )
        _record_scan_failure(document.pk, exc)
        return ApplicationDocument.objects.only("scan_status").get(pk=document.pk).scan_status

    now = timezone.now()
    if verdict.clean:
        status = ApplicationDocument.ScanStatus.CLEAN
        threat_name = ""
    else:
        status = ApplicationDocument.ScanStatus.REJECTED
        threat_name = verdict.threat_name[:255]
    ApplicationDocument.objects.filter(
        pk=document.pk, scan_status=ApplicationDocument.ScanStatus.SCANNING
    ).update(
        scan_status=status,
        scan_started_at=None,
        scan_completed_at=now,
        scan_engine=CLAMAV_ENGINE,
        scan_error="",
        threat_name=threat_name,
        updated_at=now,
    )
    return status


def _record_scan_failure(document_id, exc: Exception) -> None:
    with transaction.atomic():
        document = ApplicationDocument.objects.select_for_update().get(pk=document_id)
        if document.scan_status != ApplicationDocument.ScanStatus.SCANNING:
            return
        exhausted = (
            document.scan_attempts >= settings.ADMISSIONS_DOCUMENT_SCAN_MAX_ATTEMPTS
        )
        document.scan_status = (
            ApplicationDocument.ScanStatus.FAILED
            if exhausted
            else ApplicationDocument.ScanStatus.PENDING
        )
        document.scan_started_at = None
        document.scan_completed_at = timezone.now() if exhausted else None
        document.scan_engine = CLAMAV_ENGINE
        document.scan_error = str(exc)[:1000] or exc.__class__.__name__
        document.save(
            update_fields=[
                "scan_status",
                "scan_started_at",
                "scan_completed_at",
                "scan_engine",
                "scan_error",
                "updated_at",
            ]
        )

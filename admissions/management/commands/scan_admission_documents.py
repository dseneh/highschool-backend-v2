from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django_tenants.utils import get_tenant_model, schema_context

from admissions.scanning import (
    claim_pending_document_ids,
    reset_stale_document_scans,
    scan_claimed_document,
)


class Command(BaseCommand):
    help = "Scan pending admissions documents with ClamAV across tenant schemas."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--batch-size", type=int, default=20)
        parser.add_argument(
            "--poll-seconds",
            type=float,
            default=settings.ADMISSIONS_DOCUMENT_SCAN_POLL_SECONDS,
        )

    def handle(self, *args, **options):
        if not settings.ADMISSIONS_DOCUMENT_SCAN_HOST:
            raise CommandError("ADMISSIONS_DOCUMENT_SCAN_HOST must be configured.")
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1.")
        if options["poll_seconds"] <= 0:
            raise CommandError("--poll-seconds must be greater than 0.")

        while True:
            processed = self._scan_all_tenants(options["batch_size"])
            if not options["watch"]:
                self.stdout.write(self.style.SUCCESS(f"Processed {processed} document(s)."))
                return
            close_old_connections()
            time.sleep(options["poll_seconds"])

    def _scan_all_tenants(self, batch_size: int) -> int:
        processed = 0
        tenant_model = get_tenant_model()
        schema_names = list(
            tenant_model.objects.exclude(schema_name="public").values_list(
                "schema_name", flat=True
            )
        )
        for schema_name in schema_names:
            with schema_context(schema_name):
                reset_stale_document_scans()
                document_ids = claim_pending_document_ids(batch_size=batch_size)
                for document_id in document_ids:
                    scan_claimed_document(document_id)
                    processed += 1
        return processed

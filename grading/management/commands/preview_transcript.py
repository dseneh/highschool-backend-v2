"""Preview official transcript PDF for a student.

Usage:
    python manage.py preview_transcript --list-tenants
    python manage.py preview_transcript 20001 --schema ldtc --open
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.utils import ProgrammingError
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from core.models import Domain
from grading.services.transcript_pdf import build_official_transcript_pdf_bytes
from students.models import Student
from students.services.student_lookup import get_student_by_identifier


class Command(BaseCommand):
    help = "Generate an official transcript PDF for a student (local preview)."

    def add_arguments(self, parser):
        parser.add_argument(
            "student_id",
            nargs="?",
            help="Student UUID or id_number (e.g. 20001).",
        )
        parser.add_argument(
            "--output",
            "-o",
            default="/tmp/transcript-preview.pdf",
            help="Where to write the PDF (default: /tmp/transcript-preview.pdf).",
        )
        parser.add_argument(
            "--open",
            action="store_true",
            help="Open the PDF in your default viewer after writing it.",
        )
        parser.add_argument(
            "--schema",
            help="Tenant schema name (e.g. ldtc). Required unless --subdomain is set.",
        )
        parser.add_argument(
            "--subdomain",
            help="Tenant subdomain used in the UI URL (resolved to schema via public tenant table).",
        )
        parser.add_argument(
            "--list-tenants",
            action="store_true",
            help="List available tenant schemas and exit.",
        )

    def handle(self, *args, **options):
        if options["list_tenants"]:
            self._print_tenants()
            return

        student_id = options.get("student_id")
        if not student_id:
            raise CommandError(
                "Provide a student id_number (or UUID). "
                "Example: python manage.py preview_transcript 20001 --schema ldtc --open"
            )

        schema = self._resolve_schema(
            schema=options.get("schema"),
            subdomain=options.get("subdomain"),
        )
        output_path = Path(options["output"]).expanduser().resolve()

        try:
            with schema_context(schema):
                self._render_student(
                    student_id=student_id,
                    output_path=output_path,
                    open_viewer=options["open"],
                    schema=schema,
                )
        except ProgrammingError as exc:
            if "student" in str(exc).lower() and "does not exist" in str(exc).lower():
                raise CommandError(
                    f"Schema '{schema}' has no student tables. "
                    f"Use --list-tenants to see valid schema names, then rerun with "
                    f"--schema <schema_name> or --subdomain <subdomain>."
                ) from exc
            raise

    def _print_tenants(self) -> None:
        self.stdout.write("Available tenants:\n")
        with schema_context(get_public_schema_name()):
            Tenant = get_tenant_model()
            tenants = Tenant.objects.exclude(
                schema_name=get_public_schema_name()
            ).order_by("name")
            if not tenants.exists():
                self.stdout.write("  (none found)")
                return

            for tenant in tenants:
                domains = list(
                    Domain.objects.filter(tenant=tenant).values_list("domain", flat=True)
                )
                domain_hint = domains[0] if domains else "-"
                self.stdout.write(
                    f"  • {tenant.name}\n"
                    f"      schema: {tenant.schema_name}\n"
                    f"      domain: {domain_hint}\n"
                )

    def _resolve_schema(self, *, schema: str | None, subdomain: str | None) -> str:
        if schema and subdomain:
            raise CommandError("Use only one of --schema or --subdomain.")

        if schema:
            return self._validate_schema(schema)

        if subdomain:
            return self._schema_from_subdomain(subdomain)

        raise CommandError(
            "Multi-tenant app: pass --schema <schema_name> or --subdomain <subdomain>.\n"
            "Run with --list-tenants to see available tenants."
        )

    def _validate_schema(self, schema: str) -> str:
        with schema_context(get_public_schema_name()):
            Tenant = get_tenant_model()
            if not Tenant.objects.filter(schema_name=schema).exists():
                known = list(
                    Tenant.objects.exclude(schema_name=get_public_schema_name())
                    .values_list("schema_name", flat=True)
                    .order_by("schema_name")[:10]
                )
                hint = ", ".join(known) if known else "(run --list-tenants)"
                raise CommandError(
                    f"Unknown tenant schema '{schema}'. Known schemas: {hint}"
                )
        return schema

    def _schema_from_subdomain(self, subdomain: str) -> str:
        subdomain = subdomain.strip().lower()
        with schema_context(get_public_schema_name()):
            Tenant = get_tenant_model()

            tenant = Tenant.objects.filter(schema_name=subdomain).first()
            if tenant:
                return tenant.schema_name

            domain = (
                Domain.objects.filter(domain__istartswith=f"{subdomain}.")
                .select_related("tenant")
                .first()
            )
            if domain and domain.tenant_id:
                return domain.tenant.schema_name

            domain = (
                Domain.objects.filter(domain__iexact=subdomain)
                .select_related("tenant")
                .first()
            )
            if domain and domain.tenant_id:
                return domain.tenant.schema_name

        raise CommandError(
            f"No tenant found for subdomain '{subdomain}'. "
            f"Run --list-tenants or pass --schema directly."
        )

    def _render_student(
        self,
        *,
        student_id: str,
        output_path: Path,
        open_viewer: bool,
        schema: str,
    ) -> None:
        try:
            student = get_student_by_identifier(student_id)
        except Student.DoesNotExist as exc:
            raise CommandError(
                f"Student '{student_id}' not found in schema '{schema}'."
            ) from exc

        pdf_bytes = build_official_transcript_pdf_bytes(student)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(pdf_bytes)

        self.stdout.write(
            self.style.SUCCESS(
                f"[{schema}] Wrote transcript PDF for {student.get_full_name()} "
                f"({student.id_number}) to {output_path}"
            )
        )

        if open_viewer:
            webbrowser.open(output_path.as_uri())

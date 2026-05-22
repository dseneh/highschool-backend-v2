"""Re-materialize notification recipients for past campaigns.

Useful after a fix to ``audience.resolve_user_ids`` widens the set of
eligible recipients — e.g. when students/teachers with placeholder
``@local.user`` emails were previously excluded from the "all" scope. This
command walks every campaign in the target schema(s), re-resolves the
audience, and creates ``Notification`` rows for any newly-included users.
Existing rows are left untouched (``ignore_conflicts=True``).
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from notifications.models import Notification, NotificationCampaign
from notifications.services.audience import resolve_user_ids


class Command(BaseCommand):
    help = (
        "Re-materialize recipients for past notification campaigns. "
        "Adds Notification rows for users newly covered by the audience "
        "resolver without touching existing rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            type=str,
            help="Tenant schema to backfill.",
        )
        parser.add_argument(
            "--all-schemas",
            action="store_true",
            help="Backfill every tenant schema except public.",
        )
        parser.add_argument(
            "--campaign-id",
            type=str,
            help="Restrict to a single campaign id (only used with --schema).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **options):
        schema_name = options.get("schema")
        all_schemas = bool(options.get("all_schemas"))
        campaign_id = options.get("campaign_id")
        dry_run = bool(options.get("dry_run"))

        if schema_name and all_schemas:
            raise CommandError("Use either --schema or --all-schemas, not both.")

        public_schema = get_public_schema_name()
        Tenant = get_tenant_model()

        if all_schemas:
            target_schemas = list(
                Tenant.objects.exclude(schema_name=public_schema).values_list(
                    "schema_name", flat=True
                )
            )
        elif schema_name:
            if schema_name == public_schema:
                raise CommandError(
                    "Notification tables are not in the public schema."
                )
            target_schemas = [schema_name]
        else:
            current = getattr(connection, "schema_name", public_schema)
            if current == public_schema:
                raise CommandError(
                    "You are on the public schema. Pass --schema=<tenant> "
                    "or --all-schemas."
                )
            target_schemas = [current]

        if not target_schemas:
            self.stdout.write(self.style.WARNING("No tenant schemas found."))
            return

        grand_total = 0
        for schema in target_schemas:
            added = self._backfill_schema(schema, campaign_id, dry_run)
            grand_total += added

        verb = "Would add" if dry_run else "Added"
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {verb} {grand_total} new Notification row(s) across "
                f"{len(target_schemas)} schema(s)."
            )
        )

    def _backfill_schema(self, schema: str, campaign_id, dry_run: bool) -> int:
        self.stdout.write(f"Backfilling schema: {schema}")
        with schema_context(schema):
            qs = NotificationCampaign.objects.all()
            if campaign_id:
                qs = qs.filter(id=campaign_id)
            qs = qs.order_by("created_at")
            total_added = 0
            for campaign in qs:
                added = self._backfill_campaign(campaign, dry_run)
                total_added += added
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ {schema}: {total_added} new row(s) across "
                    f"{qs.count()} campaign(s)."
                )
            )
            return total_added

    def _backfill_campaign(self, campaign: NotificationCampaign, dry_run: bool) -> int:
        sender = campaign.created_by
        if sender is None:
            self.stdout.write(
                self.style.WARNING(
                    f"  · {campaign.id} skipped (no created_by)."
                )
            )
            return 0

        recipient_ids = resolve_user_ids(
            campaign.audience or {},
            sender,
            category=campaign.category,
        )
        if not recipient_ids:
            return 0

        existing = set(
            Notification.objects.filter(campaign=campaign).values_list(
                "recipient_id", flat=True
            )
        )
        missing = [uid for uid in recipient_ids if uid not in existing]
        if not missing:
            return 0

        if dry_run:
            self.stdout.write(
                f"  · {campaign.id} '{campaign.title[:40]}' → "
                f"{len(missing)} missing row(s)"
            )
            return len(missing)

        rows = [
            Notification(
                campaign=campaign,
                recipient_id=uid,
                created_by=sender,
                updated_by=sender,
            )
            for uid in missing
        ]
        Notification.objects.bulk_create(rows, ignore_conflicts=True)
        campaign.recipient_count = (campaign.recipient_count or 0) + len(missing)
        campaign.save(update_fields=["recipient_count", "updated_at"])
        self.stdout.write(
            f"  · {campaign.id} '{campaign.title[:40]}' → added {len(missing)} row(s)"
        )
        return len(missing)

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.utils import ProgrammingError
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from notifications.models import NotificationCampaign, NotificationRule, TenantNotificationSettings


DEFAULT_RULES = [
    {
        "event_type": NotificationRule.EventType.GRADE_PUBLISHED,
        "title_template": "Grades published for {student_name}",
        "body_template": (
            "Grades have been published for {student_name}. "
            "Please sign in to view the latest results."
        ),
        "category": NotificationCampaign.Category.GRADE,
        "channels": ["in_app", "email"],
    },
    {
        "event_type": NotificationRule.EventType.PAYMENT_DUE_REMINDER,
        "title_template": "Payment reminder: due {due_date}",
        "body_template": (
            "A payment is due on {due_date} for {student_name}. "
            "Please review your account balance in the portal."
        ),
        "category": NotificationCampaign.Category.FINANCE,
        "channels": ["in_app", "email"],
        "lead_days": 7,
    },
    {
        "event_type": NotificationRule.EventType.ATTENDANCE_ABSENT,
        "title_template": "Absence recorded for {student_name}",
        "body_template": (
            "{student_name} was marked absent on {date}. "
            "Contact the school if you have questions."
        ),
        "category": NotificationCampaign.Category.ALERT,
        "channels": ["in_app", "email"],
        "enabled": False,
    },
    {
        "event_type": NotificationRule.EventType.TRANSCRIPT_REQUESTED,
        "title_template": "New transcript request from {student_name}",
        "body_template": (
            "{student_name} ({student_id_number}) submitted an official transcript request."
            "{student_note_suffix} Review it in the transcript queue."
        ),
        "category": NotificationCampaign.Category.GRADE,
        "channels": ["in_app", "email"],
        "enabled": True,
    },
    {
        "event_type": NotificationRule.EventType.TRANSCRIPT_APPROVED,
        "title_template": "Transcript access approved",
        "body_template": (
            "Your official transcript request has been approved. "
            "You can {delivery_hint}."
        ),
        "category": NotificationCampaign.Category.GRADE,
        "channels": ["in_app", "email"],
        "enabled": True,
    },
    {
        "event_type": NotificationRule.EventType.TRANSCRIPT_DENIED,
        "title_template": "Transcript request update",
        "body_template": (
            "Your official transcript request was not approved."
            "{admin_note_suffix} Contact the school office if you have questions."
        ),
        "category": NotificationCampaign.Category.GRADE,
        "channels": ["in_app", "email"],
        "enabled": True,
    },
]

TRANSCRIPT_RULE_SYNC_FIELDS = (
    "title_template",
    "body_template",
    "category",
    "channels",
    "enabled",
)


class Command(BaseCommand):
    help = (
        "Seed default notification automation rules for tenant schema(s). "
        "Notifications tables live in tenant schemas only — use --schema or --all-schemas."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            type=str,
            help="Tenant schema name to seed (e.g. school subdomain schema).",
        )
        parser.add_argument(
            "--all-schemas",
            action="store_true",
            help="Seed all tenant schemas except public.",
        )
        parser.add_argument(
            "--migrate-first",
            action="store_true",
            help="Run migrate_schemas for the notifications app before seeding.",
        )

    def handle(self, *args, **options):
        schema_name = options.get("schema")
        all_schemas = bool(options.get("all_schemas"))
        migrate_first = bool(options.get("migrate_first"))

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
                    "Notification tables are not in the public schema. "
                    "Pass a tenant schema name, e.g. --schema=<your_school_schema>."
                )
            target_schemas = [schema_name]
        else:
            current = getattr(connection, "schema_name", public_schema)
            if current == public_schema:
                raise CommandError(
                    "You are on the public schema. Notification tables exist only on tenants. "
                    "Run: python manage.py seed_notification_rules --schema=<tenant_schema> "
                    "or: python manage.py seed_notification_rules --all-schemas --migrate-first"
                )
            target_schemas = [current]

        if not target_schemas:
            self.stdout.write(self.style.WARNING("No tenant schemas found."))
            return

        total_created = 0
        for target_schema in target_schemas:
            self.stdout.write(f"Seeding notification rules for schema: {target_schema}")
            if migrate_first:
                call_command(
                    "migrate_schemas",
                    "notifications",
                    schema_name=target_schema,
                    verbosity=0,
                )

            try:
                with schema_context(target_schema):
                    created = self._seed_rules()
                    TenantNotificationSettings.get_solo()
            except ProgrammingError as exc:
                if "notification_rule" in str(exc) or "does not exist" in str(exc):
                    raise CommandError(
                        f"Notification tables are missing in schema '{target_schema}'. "
                        f"Run: python manage.py migrate_schemas notifications -s {target_schema}"
                    ) from exc
                raise

            total_created += created
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ {target_schema}: {created} new rule(s) (defaults ensured)."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(f"Done. {total_created} new rule(s) across {len(target_schemas)} schema(s).")
        )

    def _seed_rules(self) -> int:
        created = 0
        for spec in DEFAULT_RULES:
            event_type = spec["event_type"]
            defaults = {k: v for k, v in spec.items() if k != "event_type"}
            rule, was_created = NotificationRule.objects.get_or_create(
                event_type=event_type,
                defaults=defaults,
            )
            if was_created:
                created += 1
                continue

            if not event_type.startswith("transcript_"):
                continue

            updates = {}
            for field in TRANSCRIPT_RULE_SYNC_FIELDS:
                if field in defaults and getattr(rule, field) != defaults[field]:
                    updates[field] = defaults[field]
            if updates:
                for field, value in updates.items():
                    setattr(rule, field, value)
                rule.save(update_fields=[*updates.keys(), "updated_at"])
        return created

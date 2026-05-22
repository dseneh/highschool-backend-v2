from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from finance.models import _calculate_next_due_date_dynamic
from notifications.models import NotificationCampaign, NotificationRule, TenantNotificationSettings
from notifications.services.campaign_send import create_and_send_campaign
from students.models import Enrollment


class Command(BaseCommand):
    help = "Send payment due reminder notifications to parents (per tenant schema)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            type=str,
            help="Tenant schema name (default: current connection schema)",
        )

    def handle(self, *args, **options):
        schema = options.get("schema") or connection.schema_name
        if schema == "public":
            self.stderr.write("Run this command in a tenant context or pass --schema.")
            return

        from django_tenants.utils import schema_context

        with schema_context(schema):
            self._run_for_tenant()

    def _run_for_tenant(self):
        settings = TenantNotificationSettings.get_solo()
        rule = NotificationRule.objects.filter(
            event_type=NotificationRule.EventType.PAYMENT_DUE_REMINDER,
            enabled=True,
        ).first()
        if not rule:
            self.stdout.write("Payment due reminder rule is disabled or missing.")
            return

        lead_days = rule.lead_days or settings.payment_reminder_lead_days
        today = timezone.now().date()
        window_end = today + timedelta(days=lead_days)

        sent_campaigns = 0
        for enrollment in Enrollment.objects.filter(active=True).select_related(
            "student", "academic_year"
        ):
            next_due_iso = _calculate_next_due_date_dynamic(enrollment)
            if not next_due_iso:
                continue
            from datetime import date

            next_due = date.fromisoformat(next_due_iso)
            if next_due < today or next_due > window_end:
                continue

            if self._recent_reminder_sent(enrollment.student_id, next_due_iso):
                continue

            student = enrollment.student
            student_name = student.get_full_name() if hasattr(student, "get_full_name") else str(student)
            audience = {
                "scope": "parents_of_students",
                "student_ids": [str(student.id)],
            }
            context_title = rule.title_template or "Payment reminder: due {due_date}"
            context_body = rule.body_template or (
                "A payment is due on {due_date} for {student_name}."
            )

            create_and_send_campaign(
                title=context_title.format(
                    student_name=student_name,
                    due_date=next_due_iso,
                ),
                body=context_body.format(
                    student_name=student_name,
                    due_date=next_due_iso,
                    amount_due="",
                ),
                category=rule.category,
                channels=rule.channels or ["in_app", "email"],
                audience=audience,
                source=NotificationCampaign.Source.RULE,
                created_by=None,
                rule=rule,
            )
            sent_campaigns += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent_campaigns} payment reminder campaign(s)."))

    def _recent_reminder_sent(self, student_id, due_date_iso: str) -> bool:
        """Avoid duplicate reminders for the same student/due date within 24 hours."""
        since = timezone.now() - timedelta(hours=24)
        return NotificationCampaign.objects.filter(
            source=NotificationCampaign.Source.RULE,
            rule__event_type=NotificationRule.EventType.PAYMENT_DUE_REMINDER,
            created_at__gte=since,
            audience__student_ids__contains=[str(student_id)],
            title__icontains=due_date_iso,
        ).exists()

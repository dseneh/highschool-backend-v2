from django.core.management.base import BaseCommand

from billing.services.reminders import send_all_billing_reminders


class Command(BaseCommand):
    help = "Email tenant admins about complimentary access ending, renewals, and overdue payments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count tenants without sending emails.",
        )

    def handle(self, *args, **options):
        totals = send_all_billing_reminders(dry_run=options["dry_run"])
        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: would check {totals['tenants_checked']} tenant(s)."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Checked {totals['tenants_checked']} tenant(s); sent {totals['emails_sent']} reminder email(s)."
            )
        )

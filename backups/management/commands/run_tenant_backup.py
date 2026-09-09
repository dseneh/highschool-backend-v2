from django.core.management.base import BaseCommand, CommandError

from backups.services import run_backup


class Command(BaseCommand):
    help = "Run a queued tenant backup by backup UUID."

    def add_arguments(self, parser):
        parser.add_argument("backup_id")

    def handle(self, *args, **options):
        try:
            backup = run_backup(options["backup_id"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Backup {backup.id} is available at {backup.storage_key}"))

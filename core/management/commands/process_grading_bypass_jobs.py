import time

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import GradingBypassOperation
from core.services.grading_bypass import run_bypass_job


class Command(BaseCommand):
    help = "Process persisted grading bypass jobs outside the web workers."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, **options):
        while True:
            processed = self.process_one()
            if not options["loop"]:
                return
            if not processed:
                time.sleep(max(options["interval"], 0.5))

    def process_one(self):
        with transaction.atomic():
            operation = (
                GradingBypassOperation.objects.select_for_update()
                .filter(status=GradingBypassOperation.Status.PENDING)
                .order_by("created_at")
                .first()
            )
            if operation is None:
                return False
            operation_id = str(operation.pk)
            self.stdout.write(f"Claiming grading bypass job {operation_id}")

        run_bypass_job(operation_id)
        self.stdout.write(f"Finished grading bypass job {operation_id}")
        return True

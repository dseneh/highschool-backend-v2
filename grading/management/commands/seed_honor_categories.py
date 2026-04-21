"""Seed the tenant's default honor categories.

Usage:
    python manage.py seed_honor_categories [--force]

Without --force, the command is a no-op when any HonorCategory already exists.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from grading.models import HonorCategory


DEFAULT_HONOR_CATEGORIES = [
    # label, min, max, order, color
    ("Principal's List", Decimal("95"), Decimal("100"), 1, "#7c3aed"),
    ("Honor Roll", Decimal("90"), Decimal("94.99"), 2, "#2563eb"),
    ("Honorable Mention", Decimal("85"), Decimal("89.99"), 3, "#0d9488"),
]


class Command(BaseCommand):
    help = "Seed the tenant's default honor categories."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace any existing honor categories with the defaults.",
        )

    def handle(self, *args, **options):
        force = options.get("force", False)

        if HonorCategory.objects.exists():
            if not force:
                self.stdout.write(self.style.WARNING(
                    "Honor categories already exist. Pass --force to overwrite."
                ))
                return
            HonorCategory.objects.all().delete()
            self.stdout.write("Removed existing honor categories.")

        created = []
        for label, min_avg, max_avg, order, color in DEFAULT_HONOR_CATEGORIES:
            obj = HonorCategory.objects.create(
                label=label,
                min_average=min_avg,
                max_average=max_avg,
                order=order,
                color=color,
            )
            created.append(obj)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(created)} honor categories."
        ))

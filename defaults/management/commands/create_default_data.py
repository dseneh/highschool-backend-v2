from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import Tenant
from defaults.run import run_data_creation

User = get_user_model()


class Command(BaseCommand):
    help = "Create default data for a specific school"

    def add_arguments(self, parser):
        parser.add_argument(
            "--school-id",
            type=int,
            help="School ID to create default data for",
            required=True,
        )
        parser.add_argument(
            "--user-id",
            type=int,
            help="User ID to use as creator (defaults to first superuser)",
            required=False,
        )

    def handle(self, *args, **options):
        school_id = options["school_id"]
        user_id = options.get("user_id")

        try:
            school = Tenant.objects.get(id=school_id)
        except Tenant.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"School with ID {school_id} does not exist")
            )
            return

        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"User with ID {user_id} does not exist")
                )
                return
        else:
            # Use first superuser if no user specified
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                self.stdout.write(
                    self.style.ERROR(
                        "No superuser found. Please create a superuser first."
                    )
                )
                return

        self.stdout.write(f"Creating default data for school: {school.name}")
        self.stdout.write(f"Using user: {user.username} ({user.email})")

        try:
            run_data_creation(school, user)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully created default data for {school.name}"
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error creating default data: {str(e)}")
            )

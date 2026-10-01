from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context
from core.models import Tenant
from students.models import StudentGuardian
from users.models import ParentProfile
from users.parent_portal import reconcile_parent


class Command(BaseCommand):
    help = "Report unverified guardian counts; --apply repairs verified indexes/roles only."

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        tenant = Tenant.objects.get(schema_name=options["schema"])
        with schema_context(tenant.schema_name):
            self.stdout.write(f"Unverified guardian rows (manual review): {StudentGuardian.objects.filter(portal_state='unverified').count()}")
            profile_ids = set(StudentGuardian.objects.exclude(parent_profile_id=None).values_list("parent_profile_id", flat=True))
            profile_ids.update(tenant.parentstudentlink_set.values_list("profile_id", flat=True))
            for profile in ParentProfile.objects.filter(pk__in=profile_ids):
                if options["apply"]:
                    reconcile_parent(profile, tenant)
            self.stdout.write(f"{'Reconciled' if options['apply'] else 'Would reconcile'} {len(profile_ids)} verified profiles; no legacy links activated.")

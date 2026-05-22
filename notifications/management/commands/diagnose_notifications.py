"""Diagnose why a user might not be receiving notifications.

Examples:
    # Inspect everything for one tenant:
    python manage.py diagnose_notifications --schema=<tenant_schema>

    # Focus on a specific user (email or id_number):
    python manage.py diagnose_notifications --schema=<tenant_schema> \
        --user=student.S0001@local.user

    # Show what `scope=all` would target right now:
    python manage.py diagnose_notifications --schema=<tenant_schema> \
        --resolve-all
"""

from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context

from notifications.models import Notification, NotificationCampaign
from notifications.services.audience import (
    get_tenant_user_queryset,
    resolve_user_ids,
)
from users.models import User


class Command(BaseCommand):
    help = "Diagnose notification delivery for a tenant and (optionally) one user."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            required=True,
            type=str,
            help="Tenant schema name (must not be public).",
        )
        parser.add_argument(
            "--user",
            type=str,
            help="User email, username, or id_number to inspect.",
        )
        parser.add_argument(
            "--resolve-all",
            action="store_true",
            help="Print the audience resolution for scope=all.",
        )
        parser.add_argument(
            "--campaign-id",
            type=str,
            help="Re-resolve a specific campaign's audience and compare to its rows.",
        )

    def handle(self, *args, **options):
        schema = options["schema"]
        if schema == get_public_schema_name():
            raise CommandError("Pass a tenant schema, not public.")

        target_user = options.get("user")
        resolve_all = bool(options.get("resolve_all"))
        campaign_id = options.get("campaign_id")

        with schema_context(schema):
            self._inspect_tenant_users(schema)
            if resolve_all:
                self._inspect_all_audience()
            if target_user:
                self._inspect_user(target_user)
            if campaign_id:
                self._inspect_campaign(campaign_id)

    # -----------------------------------------------------------------
    def _inspect_tenant_users(self, schema):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n== Tenant {schema} =="))
        qs = get_tenant_user_queryset()
        users = list(qs.values("id", "email", "role", "account_type", "status"))
        self.stdout.write(
            f"Tenant members (UserTenantPermissions ∩ ACTIVE): {len(users)}"
        )
        role_counts = Counter(u.get("role") or "(none)" for u in users)
        for role, count in sorted(role_counts.items()):
            self.stdout.write(f"  - role={role}: {count}")

        placeholder = [
            u for u in users if (u.get("email") or "").endswith("@local.user")
        ]
        self.stdout.write(
            f"  - of those, {len(placeholder)} have placeholder @local.user emails"
        )

    def _inspect_all_audience(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\n== Resolve scope=all =="))
        sender = User.objects.filter(role__iexact="admin").first()
        if sender is None:
            sender = User.objects.first()
        if sender is None:
            self.stdout.write(self.style.WARNING("No users found."))
            return
        ids = resolve_user_ids({"scope": "all"}, sender, category="announcement")
        self.stdout.write(
            f"resolve_user_ids(scope=all) → {len(ids)} users would receive."
        )

    def _inspect_user(self, identifier):
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"\n== Inspect user '{identifier}' ==")
        )
        with schema_context(get_public_schema_name()):
            user = (
                User.objects.filter(email__iexact=identifier).first()
                or User.objects.filter(username__iexact=identifier).first()
                or User.objects.filter(id_number__iexact=identifier).first()
            )
        if user is None:
            self.stdout.write(self.style.ERROR("  user not found in public schema."))
            return

        self.stdout.write(
            f"  id={user.id}  role={user.role}  account_type={user.account_type}\n"
            f"  email={user.email}  is_active={user.is_active}  status={user.status}"
        )

        in_tenant = get_tenant_user_queryset().filter(id=user.id).exists()
        self.stdout.write(
            f"  in current tenant queryset? {self.style.SUCCESS('yes') if in_tenant else self.style.ERROR('no')}"
        )

        from tenant_users.permissions.models import UserTenantPermissions

        utp = UserTenantPermissions.objects.filter(profile_id=user.id).first()
        if utp is None:
            self.stdout.write(self.style.ERROR("  no UserTenantPermissions row in this tenant"))
        else:
            self.stdout.write(
                f"  UserTenantPermissions: is_active={utp.is_active}"
            )

        total = Notification.objects.filter(recipient=user).count()
        unread = Notification.objects.filter(recipient=user, read_at__isnull=True).count()
        self.stdout.write(
            f"  notifications: total={total}  unread={unread}"
        )

        # Most recent 5
        recent = (
            Notification.objects.filter(recipient=user)
            .select_related("campaign")
            .order_by("-created_at")[:5]
        )
        for n in recent:
            self.stdout.write(
                f"    · {n.created_at:%Y-%m-%d %H:%M}  "
                f"{'unread' if n.read_at is None else 'read'}  "
                f"{n.campaign.title[:60]}"
            )

    def _inspect_campaign(self, campaign_id):
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"\n== Inspect campaign {campaign_id} ==")
        )
        try:
            campaign = NotificationCampaign.objects.get(id=campaign_id)
        except NotificationCampaign.DoesNotExist:
            self.stdout.write(self.style.ERROR("  campaign not found"))
            return

        existing = Notification.objects.filter(campaign=campaign).count()
        self.stdout.write(
            f"  audience={campaign.audience}  "
            f"category={campaign.category}  channels={campaign.channels}\n"
            f"  recipient_count column={campaign.recipient_count}  "
            f"existing Notification rows={existing}"
        )

        if not campaign.created_by_id:
            self.stdout.write(self.style.WARNING("  no created_by → cannot re-resolve."))
            return

        resolved = resolve_user_ids(
            campaign.audience or {},
            campaign.created_by,
            category=campaign.category,
        )
        existing_ids = set(
            Notification.objects.filter(campaign=campaign).values_list(
                "recipient_id", flat=True
            )
        )
        missing = [uid for uid in resolved if uid not in existing_ids]
        extra = [uid for uid in existing_ids if uid not in resolved]
        self.stdout.write(
            f"  re-resolve → {len(resolved)} recipients "
            f"(missing rows: {len(missing)}, extra rows: {len(extra)})"
        )

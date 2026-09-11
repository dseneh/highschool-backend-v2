from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.permissions import BasePermission

from backups.policies import effective_policy
from core.models import Tenant


class TenantBackupCapabilityPermission(BasePermission):
    """Enforce platform backup capability switches for tenant-originated API actions.

    Platform superusers intentionally bypass these tenant-facing gates so
    EzySchool can still perform emergency/operational recovery actions.
    """

    message = "This backup or restore capability has been disabled for this workspace by EzySchool."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if user and getattr(user, "is_superuser", False):
            return True

        action = getattr(view, "action", None)
        capability = {
            "create": "manual_backups_allowed",
            "request_restore": "restore_requests_allowed",
            "execute": "restore_execution_allowed",
            "retry": "restore_execution_allowed",
        }.get(action)
        if capability is None:
            return True

        schema_name = connection.schema_name
        if not schema_name or schema_name == get_public_schema_name():
            return True

        with schema_context(get_public_schema_name()):
            try:
                tenant = Tenant.objects.get(schema_name=schema_name)
            except Tenant.DoesNotExist:
                self.message = "Tenant backup policy could not be resolved."
                return False
            policy = effective_policy(tenant)

        if not getattr(policy, "backups_enabled", True):
            self.message = "Backup and recovery has been paused for this workspace by EzySchool."
            return False

        allowed = bool(getattr(policy, capability))
        if not allowed:
            labels = {
                "manual_backups_allowed": "Manual backups",
                "restore_requests_allowed": "Restore requests",
                "restore_execution_allowed": "Restore execution",
            }
            self.message = f"{labels[capability]} have been disabled for this workspace by EzySchool."
        return allowed

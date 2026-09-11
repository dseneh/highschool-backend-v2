from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from auditlog.models import LogEntry
from authorization.drf import RBACPermission
from backups.models import TenantBackup, TenantRestoreRequest
from common.permissions import IsSuperAdmin
from core.models import Tenant


def _actor_summary(actor):
    if not actor:
        return None
    name = " ".join(
        part for part in [getattr(actor, "first_name", ""), getattr(actor, "last_name", "")] if part
    ).strip()
    return {
        "id": str(actor.pk),
        "id_number": getattr(actor, "id_number", None),
        "name": name or getattr(actor, "email", "") or str(actor.pk),
    }


def _message_for(entry, changes):
    status_change = changes.get("status") if isinstance(changes, dict) else None
    if isinstance(status_change, (list, tuple)) and len(status_change) == 2:
        old, new = status_change
        if not old:
            return f"Status set to {str(new).replace('_', ' ')}"
        return f"Status changed from {str(old).replace('_', ' ')} to {str(new).replace('_', ' ')}"
    action = getattr(entry, "get_action_display", lambda: "Updated")()
    return str(action)


def _fallback_history(instance):
    actor = _actor_summary(getattr(instance, "requested_by", None))
    timestamp = getattr(instance, "requested_at", None) or getattr(instance, "created_at", None)
    if not timestamp:
        return []
    return [
        {
            "id": f"baseline-{instance.pk}",
            "action": "created",
            "timestamp": timestamp,
            "actor": actor,
            "message": f"Record created; current status is {str(instance.status).replace('_', ' ')}",
            "status_from": None,
            "status_to": instance.status,
            "changes": {},
        }
    ]


def _history_for(instance):
    entries = (
        LogEntry.objects.get_for_object(instance)
        .select_related("actor")
        .order_by("-timestamp")
    )
    history = []
    for entry in entries:
        try:
            changes = entry.changes_dict or {}
        except Exception:
            changes = {}
        status_change = changes.get("status") if isinstance(changes, dict) else None
        status_from = None
        status_to = None
        if isinstance(status_change, (list, tuple)) and len(status_change) == 2:
            status_from, status_to = status_change
        history.append(
            {
                "id": entry.pk,
                "action": str(getattr(entry, "get_action_display", lambda: "Updated")()).lower(),
                "timestamp": entry.timestamp,
                "actor": _actor_summary(entry.actor),
                "message": _message_for(entry, changes),
                "status_from": status_from,
                "status_to": status_to,
                "changes": changes,
            }
        )
    return history or _fallback_history(instance)


class TenantHistoryMixin:
    permission_classes = [RBACPermission]
    permission_map = {"get": "backups.view"}

    def _tenant(self):
        schema_name = connection.schema_name
        if not schema_name or schema_name == get_public_schema_name():
            raise NotFound("Backup and recovery are not available in this workspace.")
        with schema_context(get_public_schema_name()):
            try:
                return Tenant.objects.get(schema_name=schema_name)
            except Tenant.DoesNotExist as exc:
                raise NotFound("Tenant not found.") from exc


class TenantBackupHistoryView(TenantHistoryMixin, APIView):
    def get(self, request, pk):
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            try:
                backup = TenantBackup.objects.select_related("requested_by").get(pk=pk, tenant=tenant)
            except (TenantBackup.DoesNotExist, ValueError) as exc:
                raise NotFound("Backup not found.") from exc
            return Response(_history_for(backup))


class TenantRestoreHistoryView(TenantHistoryMixin, APIView):
    def get(self, request, pk):
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            try:
                restore = TenantRestoreRequest.objects.select_related("requested_by").get(pk=pk, tenant=tenant)
            except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
                raise NotFound("Restore request not found.") from exc
            return Response(_history_for(restore))


class PlatformBackupHistoryView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        if connection.schema_name != get_public_schema_name():
            raise NotFound("Platform backup administration is only available in the public workspace.")
        try:
            backup = TenantBackup.objects.select_related("requested_by").get(pk=pk)
        except (TenantBackup.DoesNotExist, ValueError) as exc:
            raise NotFound("Backup not found.") from exc
        return Response(_history_for(backup))


class PlatformRestoreHistoryView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        if connection.schema_name != get_public_schema_name():
            raise NotFound("Platform restore administration is only available in the public workspace.")
        try:
            restore = TenantRestoreRequest.objects.select_related("requested_by").get(pk=pk)
        except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
            raise NotFound("Restore request not found.") from exc
        return Response(_history_for(restore))

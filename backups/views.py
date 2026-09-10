from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from authorization.drf import RBACPermission
from backups.models import TenantBackup, TenantRestoreRequest
from backups.restore_services import RestoreError, refresh_restore_readiness, request_restore
from backups.serializers import (
    RestoreRequestCreateSerializer,
    TenantBackupSerializer,
    TenantRestoreRequestSerializer,
)
from backups.services import BackupError, request_backup
from core.models import Tenant


class TenantContextMixin:
    def _tenant(self):
        schema_name = connection.schema_name
        if not schema_name or schema_name == get_public_schema_name():
            raise NotFound("Backup and recovery are not available in this workspace.")
        with schema_context(get_public_schema_name()):
            try:
                return Tenant.objects.get(schema_name=schema_name)
            except Tenant.DoesNotExist as exc:
                raise NotFound("Tenant not found.") from exc


class TenantBackupViewSet(TenantContextMixin, viewsets.ReadOnlyModelViewSet):
    """Tenant-admin backup history, ad hoc backup requests, and restore requests."""

    serializer_class = TenantBackupSerializer
    permission_classes = [RBACPermission]
    permission_map = {
        "list": "backups.view",
        "retrieve": "backups.view",
        "create": "backups.create",
        "request_restore": "restore.request",
    }
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            return list(
                TenantBackup.objects.filter(tenant=tenant)
                .select_related("requested_by")
                .order_by("-requested_at")
            )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(self.get_serializer(queryset, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            try:
                backup = TenantBackup.objects.select_related("requested_by").get(
                    pk=kwargs[self.lookup_field], tenant=tenant
                )
            except (TenantBackup.DoesNotExist, ValueError) as exc:
                raise NotFound("Backup not found.") from exc
            data = self.get_serializer(backup).data
        return Response(data)

    def create(self, request, *args, **kwargs):
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            try:
                backup = request_backup(tenant=tenant, requested_by=request.user)
            except BackupError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            data = self.get_serializer(backup).data
        return Response(data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="restore-request")
    def request_restore(self, request, pk=None):
        tenant = self._tenant()
        input_serializer = RestoreRequestCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        with schema_context(get_public_schema_name()):
            try:
                backup = TenantBackup.objects.get(pk=pk, tenant=tenant)
            except (TenantBackup.DoesNotExist, ValueError) as exc:
                raise NotFound("Backup not found.") from exc
            try:
                restore_request = request_restore(
                    tenant=tenant,
                    backup=backup,
                    requested_by=request.user,
                    reason=input_serializer.validated_data.get("reason", ""),
                )
            except RestoreError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            data = TenantRestoreRequestSerializer(restore_request).data
        return Response(data, status=status.HTTP_202_ACCEPTED)


class TenantRestoreRequestViewSet(TenantContextMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only tenant view of restore requests and their safety-backup readiness."""

    serializer_class = TenantRestoreRequestSerializer
    permission_classes = [RBACPermission]
    permission_map = {
        "list": "backups.view",
        "retrieve": "backups.view",
    }
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            requests = list(
                TenantRestoreRequest.objects.filter(tenant=tenant)
                .select_related("backup", "safety_backup", "requested_by", "approved_by", "rejected_by")
                .order_by("-requested_at")
            )
            for restore_request in requests:
                refresh_restore_readiness(restore_request)
            return requests

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(self.get_serializer(queryset, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            try:
                restore_request = TenantRestoreRequest.objects.select_related(
                    "backup", "safety_backup", "requested_by", "approved_by", "rejected_by"
                ).get(pk=kwargs[self.lookup_field], tenant=tenant)
            except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
                raise NotFound("Restore request not found.") from exc
            restore_request = refresh_restore_readiness(restore_request)
            data = self.get_serializer(restore_request).data
        return Response(data)

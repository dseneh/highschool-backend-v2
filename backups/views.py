from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from authorization.drf import RBACPermission
from backups.models import TenantBackup
from backups.serializers import TenantBackupSerializer
from backups.services import BackupError, request_backup
from core.models import Tenant


class TenantBackupViewSet(viewsets.ReadOnlyModelViewSet):
    """Tenant-admin backup history and ad hoc backup requests.

    Backup metadata is stored in the public schema, but callers can only see
    records for the tenant selected by the current tenant middleware context.
    The API intentionally never exposes storage object keys or raw pg_dump
    errors.
    """

    serializer_class = TenantBackupSerializer
    permission_classes = [RBACPermission]
    permission_map = {
        "list": "backups.view",
        "retrieve": "backups.view",
        "create": "backups.create",
    }
    http_method_names = ["get", "post", "head", "options"]

    def _tenant(self):
        schema_name = connection.schema_name
        if not schema_name or schema_name == get_public_schema_name():
            raise NotFound("Tenant backups are not available in this workspace.")
        with schema_context(get_public_schema_name()):
            try:
                return Tenant.objects.get(schema_name=schema_name)
            except Tenant.DoesNotExist as exc:
                raise NotFound("Tenant not found.") from exc

    def get_queryset(self):
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            # Evaluation happens inside the public schema before the context
            # exits; returning a materialized list avoids a later query against
            # the tenant schema where this shared table does not live.
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

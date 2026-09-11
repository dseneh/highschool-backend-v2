from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from authorization.drf import RBACPermission
from backups.models import TenantBackup, TenantRestoreRequest
from backups.restore_services import (
    RestoreError,
    approve_restore,
    delete_restore,
    execute_restore,
    refresh_restore_readiness,
    reject_restore,
    request_restore,
    retry_restore,
)
from backups.serializers import (
    BackupRequestCreateSerializer,
    PlatformTenantBackupSerializer,
    PlatformTenantRestoreRequestSerializer,
    RestoreDecisionSerializer,
    RestoreRequestCreateSerializer,
    TenantBackupSerializer,
    TenantRestoreRequestSerializer,
)
from backups.services import BackupError, delete_backup, request_backup
from common.permissions import IsSuperAdmin
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
    serializer_class = TenantBackupSerializer
    permission_classes = [RBACPermission]
    permission_map = {
        "list": "backups.view",
        "retrieve": "backups.view",
        "create": "backups.create",
        "destroy": "backups.delete",
        "request_restore": "restore.request",
    }
    http_method_names = ["get", "post", "delete", "head", "options"]

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
        input_serializer = BackupRequestCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        with schema_context(get_public_schema_name()):
            try:
                backup = request_backup(
                    tenant=tenant,
                    requested_by=request.user,
                    reason=input_serializer.validated_data["reason"],
                )
            except BackupError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            data = self.get_serializer(backup).data
        return Response(data, status=status.HTTP_202_ACCEPTED)

    def destroy(self, request, *args, **kwargs):
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            try:
                backup = TenantBackup.objects.get(pk=kwargs[self.lookup_field], tenant=tenant)
            except (TenantBackup.DoesNotExist, ValueError) as exc:
                raise NotFound("Backup not found.") from exc
            try:
                backup = delete_backup(backup)
            except BackupError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            data = self.get_serializer(backup).data
        return Response(data, status=status.HTTP_200_OK)

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
    serializer_class = TenantRestoreRequestSerializer
    permission_classes = [RBACPermission]
    permission_map = {
        "list": "backups.view",
        "retrieve": "backups.view",
        "execute": "restore.execute",
        "retry": "restore.execute",
    }
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            requests = list(
                TenantRestoreRequest.objects.filter(tenant=tenant)
                .select_related("tenant", "backup", "safety_backup", "requested_by", "approved_by", "rejected_by")
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
                    "tenant", "backup", "safety_backup", "requested_by", "approved_by", "rejected_by"
                ).get(pk=kwargs[self.lookup_field], tenant=tenant)
            except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
                raise NotFound("Restore request not found.") from exc
            restore_request = refresh_restore_readiness(restore_request)
            data = self.get_serializer(restore_request).data
        return Response(data)

    @action(detail=True, methods=["post"], url_path="execute")
    def execute(self, request, pk=None):
        """Execute an approved restore request (tenant action).
        
        Transitions from APPROVED to EXECUTION_PENDING.
        Tenant can only execute their own restore requests.
        """
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            try:
                restore_request = TenantRestoreRequest.objects.select_related(
                    "tenant", "backup", "safety_backup"
                ).get(pk=pk, tenant=tenant)
            except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
                raise NotFound("Restore request not found.") from exc
            try:
                restore_request = execute_restore(restore_request=restore_request, executed_by=request.user)
            except RestoreError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            data = self.get_serializer(restore_request).data
        return Response(data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="retry")
    def retry(self, request, pk=None):
        """Retry a failed restore request (tenant action).
        
        Only allows retry of FAILED requests that were previously APPROVED.
        Transitions directly to EXECUTION_PENDING without second approval.
        """
        tenant = self._tenant()
        with schema_context(get_public_schema_name()):
            try:
                restore_request = TenantRestoreRequest.objects.select_related(
                    "tenant", "backup", "safety_backup"
                ).get(pk=pk, tenant=tenant)
            except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
                raise NotFound("Restore request not found.") from exc
            try:
                restore_request = retry_restore(restore_request=restore_request, retried_by=request.user)
            except RestoreError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            data = self.get_serializer(restore_request).data
        return Response(data, status=status.HTTP_202_ACCEPTED)


class PlatformBackupViewSet(viewsets.ReadOnlyModelViewSet):
    """Platform-superadmin read-only backup history across all tenants."""

    serializer_class = PlatformTenantBackupSerializer
    permission_classes = [IsSuperAdmin]
    http_method_names = ["get", "head", "options"]

    def _require_public_workspace(self):
        if connection.schema_name != get_public_schema_name():
            raise NotFound("Platform backup administration is only available in the public workspace.")

    def get_queryset(self):
        self._require_public_workspace()
        with schema_context(get_public_schema_name()):
            return list(
                TenantBackup.objects.select_related("tenant", "requested_by").order_by("-requested_at")
            )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        self._require_public_workspace()
        with schema_context(get_public_schema_name()):
            try:
                backup = TenantBackup.objects.select_related("tenant", "requested_by").get(
                    pk=kwargs[self.lookup_field]
                )
            except (TenantBackup.DoesNotExist, ValueError) as exc:
                raise NotFound("Backup not found.") from exc
            data = self.get_serializer(backup).data
        return Response(data)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Get backup summary statistics for admin UI (platform superadmin only).
        
        Returns:
        - total_backup_count: Total number of backups across all tenants
        - available_backup_count: Number of backups with status=AVAILABLE
        - total_storage_bytes: Sum of file_size for available backups only
        - protected_tenant_count: Number of active tenants with at least one available backup
        - failed_backup_count: Number of backups with status=FAILED
        - scheduled_backup_count: Number of scheduled backups across all statuses
        - upcoming_backup_count: Number of tenants due for a scheduled backup
        - next_scheduled_backup_at: Timestamp of the next scheduled backup due (or null)
        """
        self._require_public_workspace()
        with schema_context(get_public_schema_name()):
            backups = TenantBackup.objects.select_related("tenant")
            total_backup_count = backups.count()
            available_backups = backups.filter(status=TenantBackup.Status.AVAILABLE)
            available_backup_count = available_backups.count()
            total_storage_bytes = sum(b.file_size or 0 for b in available_backups)
            failed_backup_count = backups.filter(status=TenantBackup.Status.FAILED).count()
            scheduled_backups = backups.filter(backup_type=TenantBackup.BackupType.SCHEDULED)
            scheduled_backup_count = scheduled_backups.count()
            
            protected_tenant_ids = set(available_backups.values_list("tenant_id", flat=True))
            protected_tenant_count = len(protected_tenant_ids)
            
            # Compute upcoming scheduled backups
            upcoming_backup_count = 0
            next_scheduled_backup_at = None
            
            if getattr(settings, "TENANT_BACKUP_SCHEDULE_ENABLED", False):
                interval_hours = max(1, getattr(settings, "TENANT_BACKUP_SCHEDULE_INTERVAL_HOURS", 168))
                cutoff = timezone.now() - timedelta(hours=interval_hours)
                active_tenants = Tenant.objects.exclude(schema_name=get_public_schema_name()).filter(active=True)
                
                upcoming_times = []
                for tenant in active_tenants:
                    latest_scheduled = TenantBackup.objects.filter(
                        tenant=tenant,
                        backup_type=TenantBackup.BackupType.SCHEDULED,
                        status=TenantBackup.Status.AVAILABLE,
                        completed_at__isnull=False,
                    ).order_by("-completed_at").first()
                    
                    if latest_scheduled and latest_scheduled.completed_at > cutoff:
                        next_due = latest_scheduled.completed_at + timedelta(hours=interval_hours)
                    else:
                        next_due = timezone.now()
                    
                    upcoming_times.append(next_due)
                    if next_due <= timezone.now():
                        upcoming_backup_count += 1
                
                if upcoming_times:
                    next_scheduled_backup_at = min(upcoming_times).isoformat() if upcoming_times else None
            
            return Response({
                "total_backup_count": total_backup_count,
                "available_backup_count": available_backup_count,
                "total_storage_bytes": total_storage_bytes,
                "protected_tenant_count": protected_tenant_count,
                "failed_backup_count": failed_backup_count,
                "scheduled_backup_count": scheduled_backup_count,
                "upcoming_backup_count": upcoming_backup_count,
                "next_scheduled_backup_at": next_scheduled_backup_at,
            })


class PlatformRestoreRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """Platform-superadmin review queue for tenant restore requests."""

    serializer_class = PlatformTenantRestoreRequestSerializer
    permission_classes = [IsSuperAdmin]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def _require_public_workspace(self):
        if connection.schema_name != get_public_schema_name():
            raise NotFound("Platform restore administration is only available in the public workspace.")

    def get_queryset(self):
        self._require_public_workspace()
        with schema_context(get_public_schema_name()):
            requests = list(
                TenantRestoreRequest.objects.select_related(
                    "tenant", "backup", "safety_backup", "requested_by", "approved_by", "rejected_by"
                ).order_by("-requested_at")
            )
            for restore_request in requests:
                refresh_restore_readiness(restore_request)
            return requests

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        self._require_public_workspace()
        with schema_context(get_public_schema_name()):
            try:
                restore_request = TenantRestoreRequest.objects.select_related(
                    "tenant", "backup", "safety_backup", "requested_by", "approved_by", "rejected_by"
                ).get(pk=kwargs[self.lookup_field])
            except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
                raise NotFound("Restore request not found.") from exc
            restore_request = refresh_restore_readiness(restore_request)
            data = self.get_serializer(restore_request).data
        return Response(data)

    def destroy(self, request, *args, **kwargs):
        """Delete a restore request (platform superadmin only).
        
        Only allows hard delete for terminal statuses: FAILED, REJECTED, CANCELLED.
        """
        self._require_public_workspace()
        with schema_context(get_public_schema_name()):
            try:
                restore_request = TenantRestoreRequest.objects.get(pk=kwargs[self.lookup_field])
            except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
                raise NotFound("Restore request not found.") from exc
            try:
                delete_restore(restore_request=restore_request)
            except RestoreError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        self._require_public_workspace()
        input_serializer = RestoreDecisionSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        with schema_context(get_public_schema_name()):
            try:
                restore_request = TenantRestoreRequest.objects.get(pk=pk)
            except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
                raise NotFound("Restore request not found.") from exc
            try:
                restore_request = approve_restore(
                    restore_request=restore_request,
                    approved_by=request.user,
                    decision_note=input_serializer.validated_data.get("decision_note", ""),
                )
            except RestoreError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            data = self.get_serializer(restore_request).data
        return Response(data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        self._require_public_workspace()
        input_serializer = RestoreDecisionSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        with schema_context(get_public_schema_name()):
            try:
                restore_request = TenantRestoreRequest.objects.get(pk=pk)
            except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
                raise NotFound("Restore request not found.") from exc
            try:
                restore_request = reject_restore(
                    restore_request=restore_request,
                    rejected_by=request.user,
                    decision_note=input_serializer.validated_data.get("decision_note", ""),
                )
            except RestoreError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            data = self.get_serializer(restore_request).data
        return Response(data)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        """Retry a failed restore that was previously approved (platform superadmin).
        
        Only allows retry of FAILED requests where approved_at is set.
        Transitions directly to EXECUTION_PENDING without second approval.
        """
        self._require_public_workspace()
        with schema_context(get_public_schema_name()):
            try:
                restore_request = TenantRestoreRequest.objects.select_related(
                    "tenant", "backup", "safety_backup"
                ).get(pk=pk)
            except (TenantRestoreRequest.DoesNotExist, ValueError) as exc:
                raise NotFound("Restore request not found.") from exc
            try:
                restore_request = retry_restore(restore_request=restore_request, retried_by=request.user)
            except RestoreError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            data = self.get_serializer(restore_request).data
        return Response(data, status=status.HTTP_202_ACCEPTED)


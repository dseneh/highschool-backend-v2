from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from authorization.drf import RBACPermission
from backups.models import BackupPlatformSettings, TenantBackupPolicy
from backups.policies import (
    BackupPolicyError,
    effective_policy,
    ensure_schedule_state,
    get_or_create_tenant_policy,
    get_platform_backup_settings,
)
from common.permissions import IsSuperAdmin
from core.models import Tenant


OVERRIDE_FIELDS = (
    "automatic_backups_enabled",
    "frequency",
    "scheduled_time",
    "timezone",
    "scheduled_retention_days",
    "manual_retention_days",
    "safety_retention_days",
    "system_retention_days",
    "maximum_retained_scheduled_backups",
    "manual_backups_allowed",
    "restore_requests_allowed",
    "restore_execution_allowed",
    "storage_quota_bytes",
    "storage_quota_overridden",
)


class BackupPlatformSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupPlatformSettings
        fields = (
            "automatic_backups_enabled",
            "frequency",
            "scheduled_time",
            "timezone",
            "scheduled_retention_days",
            "manual_retention_days",
            "safety_retention_days",
            "system_retention_days",
            "maximum_retained_scheduled_backups",
            "tenant_manual_backups_allowed",
            "tenant_restore_requests_allowed",
            "tenant_restore_execution_allowed",
            "default_storage_quota_bytes",
            "updated_at",
        )
        read_only_fields = ("updated_at",)

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("Enter a valid IANA timezone, for example UTC or Africa/Monrovia.") from exc
        return value


class TenantBackupPolicyUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantBackupPolicy
        fields = OVERRIDE_FIELDS
        extra_kwargs = {
            "timezone": {"allow_blank": True, "required": False},
        }

    def validate_timezone(self, value):
        if not value:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("Enter a valid IANA timezone, for example UTC or Africa/Monrovia.") from exc
        return value

    def update(self, instance, validated_data):
        if "storage_quota_bytes" in validated_data and "storage_quota_overridden" not in validated_data:
            validated_data["storage_quota_overridden"] = True
        return super().update(instance, validated_data)


def _effective_payload(tenant):
    effective = effective_policy(tenant)
    return {
        "backups_enabled": effective.backups_enabled,
        "automatic_backups_enabled": effective.automatic_backups_enabled,
        "frequency": effective.frequency,
        "scheduled_time": effective.scheduled_time,
        "timezone": effective.timezone,
        "scheduled_retention_days": effective.scheduled_retention_days,
        "manual_retention_days": effective.manual_retention_days,
        "safety_retention_days": effective.safety_retention_days,
        "system_retention_days": effective.system_retention_days,
        "maximum_retained_scheduled_backups": effective.maximum_retained_scheduled_backups,
        "manual_backups_allowed": effective.manual_backups_allowed,
        "restore_requests_allowed": effective.restore_requests_allowed,
        "restore_execution_allowed": effective.restore_execution_allowed,
        "storage_quota_bytes": effective.storage_quota_bytes,
    }


def _policy_payload(tenant):
    try:
        policy = TenantBackupPolicy.objects.get(tenant=tenant)
    except TenantBackupPolicy.DoesNotExist:
        policy = None
    overrides = {field: getattr(policy, field) if policy is not None else None for field in OVERRIDE_FIELDS}
    return {
        "tenant_id": str(tenant.pk),
        "tenant_name": tenant.name,
        "tenant_schema": tenant.schema_name,
        "active": tenant.active,
        "backups_enabled": policy.backups_enabled if policy else True,
        "overrides": overrides,
        "effective": _effective_payload(tenant),
        "last_run_at": policy.last_run_at if policy else None,
        "next_run_at": policy.next_run_at if policy else None,
        "updated_at": policy.updated_at if policy else None,
    }


def _require_public_workspace():
    if connection.schema_name != get_public_schema_name():
        raise NotFound("Platform backup policy administration is only available in the public workspace.")


class TenantEffectiveBackupPolicyView(APIView):
    permission_classes = [RBACPermission]
    permission_map = {"get": "backups.view"}

    def get(self, request):
        schema_name = connection.schema_name
        if not schema_name or schema_name == get_public_schema_name():
            raise NotFound("Backup policy is not available in this workspace.")
        with schema_context(get_public_schema_name()):
            try:
                tenant = Tenant.objects.get(schema_name=schema_name)
            except Tenant.DoesNotExist as exc:
                raise NotFound("Tenant not found.") from exc
            return Response(_policy_payload(tenant))


class PlatformBackupSettingsView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        _require_public_workspace()
        with schema_context(get_public_schema_name()):
            obj = get_platform_backup_settings()
            return Response(BackupPlatformSettingsSerializer(obj).data)

    def patch(self, request):
        _require_public_workspace()
        with schema_context(get_public_schema_name()):
            with transaction.atomic():
                obj = get_platform_backup_settings()
                serializer = BackupPlatformSettingsSerializer(obj, data=request.data, partial=True)
                serializer.is_valid(raise_exception=True)
                obj = serializer.save()
            for tenant in Tenant.objects.exclude(schema_name=get_public_schema_name()).filter(active=True).iterator():
                try:
                    ensure_schedule_state(tenant, recalculate=True)
                except BackupPolicyError as exc:
                    raise ValidationError({"detail": str(exc)}) from exc
            return Response(BackupPlatformSettingsSerializer(obj).data)


class PlatformTenantBackupPolicyViewSet(viewsets.ViewSet):
    permission_classes = [IsSuperAdmin]

    def list(self, request):
        _require_public_workspace()
        with schema_context(get_public_schema_name()):
            tenants = Tenant.objects.exclude(schema_name=get_public_schema_name()).order_by("name")
            return Response([_policy_payload(tenant) for tenant in tenants])

    def retrieve(self, request, pk=None):
        _require_public_workspace()
        with schema_context(get_public_schema_name()):
            try:
                tenant = Tenant.objects.get(pk=pk)
            except (Tenant.DoesNotExist, ValueError) as exc:
                raise NotFound("Tenant not found.") from exc
            return Response(_policy_payload(tenant))

    def partial_update(self, request, pk=None):
        _require_public_workspace()
        with schema_context(get_public_schema_name()):
            try:
                tenant = Tenant.objects.get(pk=pk)
            except (Tenant.DoesNotExist, ValueError) as exc:
                raise NotFound("Tenant not found.") from exc
            policy = get_or_create_tenant_policy(tenant)
            serializer = TenantBackupPolicyUpdateSerializer(policy, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            try:
                ensure_schedule_state(tenant, recalculate=True)
            except BackupPolicyError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            return Response(_policy_payload(tenant))

    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, pk=None):
        _require_public_workspace()
        enabled = request.data.get("enabled")
        if not isinstance(enabled, bool):
            raise ValidationError({"enabled": "This field must be true or false."})
        with schema_context(get_public_schema_name()):
            try:
                tenant = Tenant.objects.get(pk=pk)
            except (Tenant.DoesNotExist, ValueError) as exc:
                raise NotFound("Tenant not found.") from exc
            policy = get_or_create_tenant_policy(tenant)
            policy.backups_enabled = enabled
            policy.save(update_fields=["backups_enabled", "updated_at"])
            ensure_schedule_state(tenant, recalculate=True)
            return Response(_policy_payload(tenant))

    @action(detail=False, methods=["post"], url_path="bulk-status")
    def bulk_status(self, request):
        _require_public_workspace()
        tenant_ids = request.data.get("tenant_ids")
        enabled = request.data.get("enabled")
        if not isinstance(tenant_ids, list) or not tenant_ids:
            raise ValidationError({"tenant_ids": "Select at least one tenant."})
        if not isinstance(enabled, bool):
            raise ValidationError({"enabled": "This field must be true or false."})
        with schema_context(get_public_schema_name()):
            tenants = list(
                Tenant.objects.exclude(schema_name=get_public_schema_name())
                .filter(pk__in=tenant_ids)
                .order_by("name")
            )
            if len(tenants) != len(set(tenant_ids)):
                raise ValidationError({"tenant_ids": "One or more tenants could not be found."})
            for tenant in tenants:
                policy = get_or_create_tenant_policy(tenant)
                policy.backups_enabled = enabled
                policy.save(update_fields=["backups_enabled", "updated_at"])
                ensure_schedule_state(tenant, recalculate=True)
            return Response([_policy_payload(tenant) for tenant in tenants])

    @action(detail=True, methods=["post"], url_path="reset")
    def reset(self, request, pk=None):
        _require_public_workspace()
        with schema_context(get_public_schema_name()):
            try:
                tenant = Tenant.objects.get(pk=pk)
            except (Tenant.DoesNotExist, ValueError) as exc:
                raise NotFound("Tenant not found.") from exc
            policy = get_or_create_tenant_policy(tenant)
            for field in OVERRIDE_FIELDS:
                if field == "timezone":
                    setattr(policy, field, "")
                elif field == "storage_quota_overridden":
                    setattr(policy, field, False)
                else:
                    setattr(policy, field, None)
            policy.save(update_fields=[*OVERRIDE_FIELDS, "updated_at"])
            try:
                ensure_schedule_state(tenant, recalculate=True)
            except BackupPolicyError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            return Response(_policy_payload(tenant), status=status.HTTP_200_OK)

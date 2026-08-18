from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsAdminOrSuperAdmin
from core.models import Feature, TenantFeatureChange, TenantFeatureEntitlement
from core.services.features import feature_access, feature_summary


def _tenant_from_request(request):
    tenant = getattr(request, "tenant", None)
    if not tenant or getattr(tenant, "schema_name", None) == "public":
        raise NotFound("A tenant workspace is required.")
    from users.tenant_access import user_has_tenant_workspace_access

    if not user_has_tenant_workspace_access(request.user, tenant):
        raise PermissionDenied("You do not have access to this workspace.")
    return tenant


def _feature_or_404(key):
    try:
        return Feature.objects.get(key=key, is_active=True)
    except Feature.DoesNotExist as exc:
        raise NotFound("Feature not found.") from exc


class TenantFeaturesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = _tenant_from_request(request)
        features = Feature.objects.filter(is_active=True)
        is_admin = IsAdminOrSuperAdmin().has_permission(request, self)
        return Response(
            {
                "can_manage": is_admin,
                "features": [feature_summary(tenant, feature) for feature in features],
            }
        )


class TenantFeatureActionView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]

    def post(self, request, key, action):
        tenant = _tenant_from_request(request)
        feature = _feature_or_404(key)
        action = action.replace("_", "-").lower()

        with transaction.atomic():
            entitlement = TenantFeatureEntitlement.objects.select_for_update().filter(
                tenant=tenant,
                feature=feature,
            ).first()

            if action == "enable":
                if not feature.is_purchasable:
                    raise ValidationError({"detail": "This feature is not available for self-service activation."})
                if feature.stripe_price_id:
                    return Response(
                        {
                            "detail": "Billing confirmation is required before this feature can be enabled.",
                            "error_code": "BILLING_CONFIRMATION_REQUIRED",
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
                if not entitlement:
                    entitlement = TenantFeatureEntitlement.objects.create(
                        tenant=tenant,
                        feature=feature,
                        source=TenantFeatureEntitlement.Source.ADDON,
                        status=TenantFeatureEntitlement.Status.ACTIVE,
                        locally_enabled=True,
                        active_from=timezone.now(),
                        updated_by=request.user,
                    )
                else:
                    entitlement.status = TenantFeatureEntitlement.Status.ACTIVE
                    entitlement.locally_enabled = True
                    entitlement.updated_by = request.user
                    entitlement.save(update_fields=["status", "locally_enabled", "updated_by", "updated_at"])
                change_action = TenantFeatureChange.Action.ENABLED
            elif action == "disable":
                if not entitlement:
                    raise ValidationError({"detail": "This feature is not enabled for this workspace."})
                entitlement.locally_enabled = False
                entitlement.updated_by = request.user
                entitlement.save(update_fields=["locally_enabled", "updated_by", "updated_at"])
                change_action = TenantFeatureChange.Action.LOCALLY_DISABLED
            elif action == "resume":
                if not entitlement:
                    raise ValidationError({"detail": "This feature is not enabled for this workspace."})
                entitlement.locally_enabled = True
                entitlement.updated_by = request.user
                entitlement.save(update_fields=["locally_enabled", "updated_by", "updated_at"])
                change_action = TenantFeatureChange.Action.LOCALLY_ENABLED
            elif action == "schedule-cancellation":
                if not entitlement or not tenant.current_period_end:
                    raise ValidationError({"detail": "An active billed subscription is required to schedule cancellation."})
                entitlement.cancel_at_period_end = True
                entitlement.active_until = tenant.current_period_end
                entitlement.updated_by = request.user
                entitlement.save(update_fields=["cancel_at_period_end", "active_until", "updated_by", "updated_at"])
                change_action = TenantFeatureChange.Action.CANCELLATION_SCHEDULED
            elif action == "resume-cancellation":
                if not entitlement:
                    raise ValidationError({"detail": "This feature is not enabled for this workspace."})
                entitlement.cancel_at_period_end = False
                entitlement.active_until = None
                entitlement.updated_by = request.user
                entitlement.save(update_fields=["cancel_at_period_end", "active_until", "updated_by", "updated_at"])
                change_action = TenantFeatureChange.Action.CANCELLATION_RESUMED
            else:
                raise NotFound("Unknown feature action.")

            TenantFeatureChange.objects.create(
                tenant=tenant,
                feature=feature,
                entitlement=entitlement,
                action=change_action,
                actor=request.user,
            )

        return Response(feature_summary(tenant, feature))


class TenantFeatureAccessView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, key):
        tenant = _tenant_from_request(request)
        feature = _feature_or_404(key)
        access = feature_access(tenant, feature.key)
        return Response(feature_summary(tenant, feature), status=status.HTTP_200_OK if access.enabled else status.HTTP_403_FORBIDDEN)

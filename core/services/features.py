from dataclasses import dataclass

from django.utils import timezone

from core.models import Feature, Tenant, TenantFeatureEntitlement


PAYROLL_FEATURE_KEY = "payroll"


@dataclass(frozen=True)
class FeatureAccess:
    key: str
    enabled: bool
    reason: str
    entitlement: TenantFeatureEntitlement | None = None


def feature_access(tenant: Tenant, feature_key: str) -> FeatureAccess:
    """Resolve access in one place so UI visibility never becomes the security gate."""
    try:
        feature = Feature.objects.get(key=feature_key, is_active=True)
    except Feature.DoesNotExist:
        return FeatureAccess(feature_key, False, "feature_unavailable")

    entitlement = TenantFeatureEntitlement.objects.filter(
        tenant=tenant,
        feature=feature,
    ).first()
    if not entitlement:
        # Keep explicitly configured legacy add-ons working until they have been
        # migrated into normalized entitlement records.
        if feature_key in (tenant.enabled_addons or []):
            return FeatureAccess(feature_key, True, "legacy_addon")
        return FeatureAccess(feature_key, False, "feature_not_entitled")

    if not entitlement.locally_enabled:
        return FeatureAccess(feature_key, False, "feature_disabled_by_tenant", entitlement)
    if entitlement.status != TenantFeatureEntitlement.Status.ACTIVE:
        return FeatureAccess(feature_key, False, entitlement.status, entitlement)
    if entitlement.active_from and entitlement.active_from > timezone.now():
        return FeatureAccess(feature_key, False, "not_yet_active", entitlement)
    if entitlement.active_until and entitlement.active_until <= timezone.now():
        return FeatureAccess(feature_key, False, "subscription_ended", entitlement)
    return FeatureAccess(feature_key, True, "active", entitlement)


def feature_summary(tenant: Tenant, feature: Feature) -> dict:
    access = feature_access(tenant, feature.key)
    entitlement = access.entitlement
    return {
        "key": feature.key,
        "name": feature.name,
        "description": feature.description,
        "category": feature.category,
        "enabled": access.enabled,
        "reason": access.reason,
        "is_purchasable": feature.is_purchasable,
        "requires_payment": bool(feature.stripe_price_id),
        "status": entitlement.status if entitlement else "not_entitled",
        "locally_enabled": entitlement.locally_enabled if entitlement else False,
        "cancel_at_period_end": entitlement.cancel_at_period_end if entitlement else False,
        "active_until": entitlement.active_until if entitlement else None,
        "limits": entitlement.limits if entitlement else {},
    }

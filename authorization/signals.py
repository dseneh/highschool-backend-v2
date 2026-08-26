from django.db import connection
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_tenants.signals import post_schema_sync
from django_tenants.utils import get_public_schema_name, schema_context

from authorization.services import (
    ensure_tenant_owner_membership,
    ensure_tenant_user_membership,
    sync_system_roles,
)
from authorization.models import Role, RolePermission, TenantMembership
from authorization.cache import (
    schedule_membership_invalidation,
    schedule_role_invalidation,
)


@receiver(post_schema_sync, dispatch_uid="authorization_seed_system_roles")
def seed_system_roles_for_new_tenant(sender, tenant, **kwargs):
    if tenant.schema_name == get_public_schema_name():
        return
    with schema_context(tenant.schema_name):
        sync_system_roles()
        ensure_tenant_owner_membership(getattr(tenant, "owner", None))


@receiver(post_save, sender="permissions.UserTenantPermissions")
def seed_rbac_membership_for_tenant_user(sender, instance, created, **kwargs):
    if not created or connection.schema_name == get_public_schema_name():
        return
    ensure_tenant_user_membership(instance.profile)


@receiver(post_delete, sender=TenantMembership)
def invalidate_deleted_membership(sender, instance, **kwargs):
    schedule_membership_invalidation(connection.schema_name, instance.user_id)


@receiver(post_delete, sender=RolePermission)
def invalidate_deleted_role_grant(sender, instance, **kwargs):
    schedule_role_invalidation(connection.schema_name, instance.role_id)


@receiver(post_delete, sender=Role)
def invalidate_deleted_role(sender, instance, **kwargs):
    schedule_role_invalidation(connection.schema_name, instance.pk)

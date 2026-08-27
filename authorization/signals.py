from django.db import connection, transaction
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


def _schedule_account_scope_sync(user_id) -> None:
    """Recalculate public User.account_scope after tenant authorization commits."""
    if not user_id or connection.schema_name == get_public_schema_name():
        return

    def sync_scope():
        try:
            from users.models import User
            from users.access_service import sync_account_scope

            with schema_context(get_public_schema_name()):
                user = User.objects.filter(pk=user_id).first()
            if user is not None:
                sync_account_scope(user)
        except Exception:
            # Authorization writes must not fail because denormalized scope
            # metadata could not be refreshed. The next access mutation/login
            # can safely recalculate it again.
            return

    transaction.on_commit(sync_scope)


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


@receiver(post_save, sender=TenantMembership)
def sync_saved_membership_scope(sender, instance, **kwargs):
    schedule_membership_invalidation(connection.schema_name, instance.user_id)
    _schedule_account_scope_sync(instance.user_id)


@receiver(post_delete, sender=TenantMembership)
def invalidate_deleted_membership(sender, instance, **kwargs):
    schedule_membership_invalidation(connection.schema_name, instance.user_id)
    _schedule_account_scope_sync(instance.user_id)


@receiver(post_delete, sender=RolePermission)
def invalidate_deleted_role_grant(sender, instance, **kwargs):
    schedule_role_invalidation(connection.schema_name, instance.role_id)


@receiver(post_delete, sender=Role)
def invalidate_deleted_role(sender, instance, **kwargs):
    schedule_role_invalidation(connection.schema_name, instance.pk)

"""Signals for shared/public authorization state."""

from django.db import connection, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_tenants.utils import get_public_schema_name, schema_context

from core.models import SharedRoleAssignment


def _schedule_account_scope_sync(user_id) -> None:
    """Refresh denormalized identity scope after a public role mutation commits."""
    if not user_id or connection.schema_name != get_public_schema_name():
        return

    def sync_scope():
        try:
            from users.access_service import sync_account_scope
            from users.models import User

            with schema_context(get_public_schema_name()):
                user = User.objects.filter(pk=user_id).first()
            if user is not None:
                sync_account_scope(user)
        except Exception:
            # A failed summary refresh must not roll back the authoritative
            # authorization write. Later access mutations/login can reconcile it.
            return

    transaction.on_commit(sync_scope)


@receiver(
    post_save,
    sender=SharedRoleAssignment,
    dispatch_uid="core_sync_account_scope_after_shared_role_save",
)
def sync_saved_shared_role_assignment_scope(sender, instance, **kwargs):
    _schedule_account_scope_sync(instance.user_id)


@receiver(
    post_delete,
    sender=SharedRoleAssignment,
    dispatch_uid="core_sync_account_scope_after_shared_role_delete",
)
def sync_deleted_shared_role_assignment_scope(sender, instance, **kwargs):
    _schedule_account_scope_sync(instance.user_id)

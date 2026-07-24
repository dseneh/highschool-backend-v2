"""Tenant deletion helpers.

Provides reusable deletion routines for tenant lifecycle operations.
"""

from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name

from core.models import Tenant


def hard_delete_tenant_workspace(tenant: Tenant) -> None:
    """Permanently delete a tenant record and its schema.

    Steps:
    1) Validate not public tenant.
    2) Run tenant_users-supported tenant cleanup via delete_tenant().
    3) Commit cleanup transaction so trigger events are flushed.
    4) DROP SCHEMA <schema_name> CASCADE in a fresh transaction.
    5) Delete tenant row in public schema via queryset delete.
    """
    public_schema = get_public_schema_name()
    if tenant.schema_name == public_schema:
        raise ValueError("Cannot hard-delete the public tenant.")

    tenant_pk = tenant.pk
    schema_name = tenant.schema_name
    public_tenant = Tenant.objects.get(schema_name=public_schema)

    # Phase 1: tenant-users cleanup. This may enqueue FK/permission trigger
    # work inside the tenant schema, so it must commit before we run DDL.
    with transaction.atomic():
        # django-tenant-users does not support calling delete() directly on the
        # tenant instance. Use its supported cleanup routine first when the
        # tenant owner differs from the public/system owner.
        #
        # If both owners are the same user, delete_tenant() hits an upstream
        # edge case and raises "Cannot remove owner from tenant" during the
        # no-op ownership transfer. For hard delete, we can safely skip that
        # branch because the tenant row and its schema are being purged.
        if tenant.owner_id != public_tenant.owner_id:
            tenant.delete_tenant()
        else:
            for user_obj in tenant.user_set.exclude(pk=tenant.owner_id):
                tenant.remove_user(user_obj)

    # Phase 2: destructive DDL in a fresh transaction after trigger queues from
    # phase 1 have been flushed.
    with transaction.atomic():
        with connection.cursor() as cursor:
            quoted_schema = connection.ops.quote_name(schema_name)
            cursor.execute(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE")

        Tenant.objects.filter(pk=tenant_pk).delete()

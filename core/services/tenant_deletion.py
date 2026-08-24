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
    2) DROP SCHEMA <schema_name> CASCADE.
    3) Delete tenant row in public schema via queryset delete.
    """
    public_schema = get_public_schema_name()
    if tenant.schema_name == public_schema:
        raise ValueError("Cannot hard-delete the public tenant.")

    tenant_pk = tenant.pk
    schema_name = tenant.schema_name

    # Permanent deletion does not need django-tenant-users' ownership transfer
    # workflow. That workflow assumes the owner and every permission row still
    # exist, which is not true for partially provisioned or stale workspaces.
    # Drop the isolated schema directly, then remove the public tenant row.
    with transaction.atomic():
        with connection.cursor() as cursor:
            quoted_schema = connection.ops.quote_name(schema_name)
            cursor.execute(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE")

        Tenant.objects.filter(pk=tenant_pk).delete()

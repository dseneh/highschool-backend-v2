"""
Utility functions for core app
"""

from django.db.models import Q
from django_tenants.utils import get_public_schema_name, schema_context


def resolve_tenant_logo_media_url(logo_field) -> str | None:
    """
    Return the media URL for a Tenant.logo ImageField.

    Tenant logos are stored under the public schema media prefix
    (``public/tenants/{schema}/...``) even when the active DB connection
    is on a tenant schema. Reading ``logo.url`` in tenant context would
    incorrectly prefix the path with the tenant schema name.
    """
    if not logo_field:
        return None

    name = getattr(logo_field, "name", "") or ""
    if name.startswith("tenants/"):
        with schema_context(get_public_schema_name()):
            try:
                return logo_field.url
            except Exception:
                return None

    try:
        return logo_field.url
    except Exception:
        return None


def get_school_object(id, school_model):
    """
    Get school object by id, workspace, or id_number.
    
    Note: In multi-tenant setup, tenant is typically identified by middleware,
    but this function can be used for backward compatibility or direct lookups.
    """
    try:
        query = Q(id=id) | Q(schema_name=id) | Q(id_number=id)
        return school_model.objects.get(query)
    except school_model.DoesNotExist:
        return None


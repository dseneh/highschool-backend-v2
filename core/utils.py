"""
Utility functions for core app
"""

from django.db.models import Q


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


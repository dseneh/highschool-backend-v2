"""Shared update behavior for resource endpoints."""

from rest_framework import viewsets
from rest_framework.response import Response

from common.update_utils import validate_partial_update


class PartialUpdateMixin:
    """Give PUT and PATCH the same validated, supplied-fields-only behavior."""

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = validate_partial_update(self.get_serializer, instance, request.data)
        # Retain each resource's authorization, audit and workflow save hook.
        self.perform_update(serializer)
        if getattr(instance, "_prefetched_objects_cache", None):
            instance._prefetched_objects_cache = {}
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)


class PartialUpdateModelViewSet(PartialUpdateMixin, viewsets.ModelViewSet):
    """Use as the base for mutable model resources; POST behavior is unchanged."""

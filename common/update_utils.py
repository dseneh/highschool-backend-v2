"""Reusable helpers for applying only meaningful model field changes."""

from rest_framework import serializers


def comparable_value(value):
    """Normalize model references and containers before equality comparison."""
    if hasattr(value, "pk"):
        return value.pk
    if isinstance(value, dict):
        return tuple(
            sorted((key, comparable_value(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(comparable_value(item) for item in value)
    return value


def filter_changed_data(instance, validated_data, *, fields=None):
    """Return submitted serializer values that differ from the model instance."""
    candidates = set(validated_data)
    if fields is not None:
        candidates.intersection_update(fields)

    return {
        field: validated_data[field]
        for field in candidates
        if comparable_value(getattr(instance, field, None))
        != comparable_value(validated_data[field])
    }


class ChangedFieldsModelSerializerMixin:
    """Skip no-op values before a ModelSerializer performs an update.

    Use this with serializers whose writable fields map directly to model
    attributes. Custom nested and many-to-many serializers should filter those
    fields explicitly before opting into this mixin.
    """

    def update(self, instance, validated_data):
        changed_data = filter_changed_data(instance, validated_data)
        if not changed_data:
            return instance
        return super().update(instance, changed_data)


class ChangedFieldsModelSerializer(
    ChangedFieldsModelSerializerMixin,
    serializers.ModelSerializer,
):
    """Convenience base class for standard model serializers."""

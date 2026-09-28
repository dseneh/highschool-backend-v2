"""Reusable helpers for applying only meaningful model field changes."""

from collections.abc import Mapping

from django.db import models, transaction
from rest_framework import serializers
from rest_framework.utils import model_meta


def validate_partial_update(
    serializer_factory, instance, data, *, raise_exception=True, **kwargs
):
    """Validate supplied fields for either PUT or PATCH, without saving.

    ``serializer_factory`` may be a serializer class or a view's
    ``get_serializer`` method. Call ``serializer.save()`` or the view's
    ``perform_update(serializer)`` after this returns. Creation must use the
    normal serializer path so its required fields remain enforced.

    Custom object validators should use ``get_update_value`` when they need
    existing values, rather than adding omitted fields to validated_data.
    Read-only fields and validation of supplied values still apply. The view
    remains responsible for permissions and domain-specific save hooks.
    """
    if instance is None:
        raise ValueError("An existing instance is required for an update.")
    kwargs["partial"] = True
    serializer = serializer_factory(instance, data=data, **kwargs)
    serializer.is_valid(raise_exception=raise_exception)
    return serializer


def get_update_value(instance, data, field, default=None):
    """Read a submitted value or the existing value without expanding an update.

    Use model/source field names after serializer deserialization. Explicit
    null, false, zero and empty strings are values, not omitted fields.
    """
    if field in data:
        return data[field]
    if isinstance(instance, Mapping):
        return instance.get(field, default)
    return getattr(instance, field, default)


def save_model_changes(instance, validated_data):
    """Persist validated concrete fields and explicit many-to-many replacements.

    This is the save half of the shared update contract. No omitted model
    columns are written. Audit timestamps advance only when something changes.
    Callers must validate and authorize first; workflow changes belong in their
    existing service or perform_update hook.
    """
    info = model_meta.get_field_info(instance)
    scalar_data, relations = {}, {}
    for field, value in validated_data.items():
        relation = info.relations.get(field)
        if relation and relation.to_many:
            values = list(value)
            current_ids = {item.pk for item in getattr(instance, field).all()}
            if current_ids != {getattr(item, "pk", item) for item in values}:
                relations[field] = values
        else:
            scalar_data[field] = value
    changed = filter_changed_data(instance, scalar_data)
    if not changed and not relations:
        return instance

    update_fields = list(changed)
    for field in instance._meta.concrete_fields:
        if getattr(field, "auto_now", False) and field.name not in update_fields:
            update_fields.append(field.name)

    def save():
        for field, value in changed.items():
            setattr(instance, field, value)
        if update_fields:
            instance.save(update_fields=update_fields)
        for field, values in relations.items():
            getattr(instance, field).set(values)

    if relations:
        with transaction.atomic():
            save()
    else:
        save()
    return instance


class PartialUpdateModelSerializer(serializers.ModelSerializer):
    """Model serializer with partial writes for existing instances only.

    Creation and list/nested creation keep normal required-field validation.
    Explicit view/service update validation should use validate_partial_update.
    """

    def __init__(self, *args, **kwargs):
        instance = args[0] if args else kwargs.get("instance")
        has_data = len(args) > 1 or "data" in kwargs
        if instance is not None and has_data:
            kwargs["partial"] = True
        super().__init__(*args, **kwargs)

    def update(self, instance, validated_data):
        serializers.raise_errors_on_nested_writes("update", self, validated_data)
        return save_model_changes(instance, validated_data)


class _ResolvedPrimaryKeyField(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        # Services may already have resolved and authorized a related object.
        if isinstance(data, self.get_queryset().model):
            return data
        return super().to_internal_value(data)


def validate_model_update(instance, data, allowed_fields, *, context=None):
    """Validate allowlisted model fields for legacy handlers and services.

    Uses the same partial-update helper without relying on output-only/nested
    response serializers. Accepts JSON, multipart mappings, FK names, FK _id
    aliases and already-resolved related model instances. Never expands input
    with defaults or stored values. Domain validation remains with the caller.
    """
    if not isinstance(data, Mapping):
        raise serializers.ValidationError({"detail": "Expected an object of fields to update."})
    if not isinstance(instance, models.Model):
        raise ValueError("An existing model instance is required for a model update.")
    model = type(instance)
    names = {field.attname: field.name for field in model._meta.concrete_fields}
    field_names = list(dict.fromkeys(names.get(name, name) for name in allowed_fields))
    payload = data.copy()
    for key in list(payload):
        if key not in allowed_fields:
            del payload[key]
    for key in list(payload):
        if names.get(key, key) != key:
            target = names[key]
            if target not in payload:
                payload[target] = payload[key]
            del payload[key]

    class ModelUpdateSerializer(PartialUpdateModelSerializer):
        serializer_related_field = _ResolvedPrimaryKeyField

    ModelUpdateSerializer.Meta = type("Meta", (), {"model": model, "fields": field_names})
    return validate_partial_update(
        ModelUpdateSerializer,
        instance,
        payload,
        context=context or {},
    )


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
    allowed = set(fields) if fields is not None else None

    return {
        field: validated_data[field]
        for field in validated_data
        if (allowed is None or field in allowed)
        and comparable_value(getattr(instance, field, None))
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
    PartialUpdateModelSerializer,
):
    """Convenience base class for standard model serializers."""

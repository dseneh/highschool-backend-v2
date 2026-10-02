# Partial updates across the backend

All supported resource PUT and PATCH handlers use the shared partial-update
contract, through a viewset base, serializer base, or the legacy field-update
adapter. Omitted fields are neither required nor replaced with defaults.
Explicit null, false, zero, empty strings and empty lists remain submitted values
and are accepted only when the field permits them. Creation still enforces its
required fields. Existing route methods, permissions and editable-field allowlists
remain in effect.

## Standard model resources

```python
from common.update_utils import PartialUpdateModelSerializer
from common.viewsets import PartialUpdateModelViewSet

class ItemSerializer(PartialUpdateModelSerializer):
    class Meta:
        model = Item
        fields = ["id", "name", "notes"]
        read_only_fields = ["id"]

class ItemViewSet(PartialUpdateModelViewSet):
    queryset = Item.objects.all()
    serializer_class = ItemSerializer
```

The viewset uses `validate_partial_update` and calls `perform_update`, retaining
resource-specific save hooks. The serializer saves changed columns only, plus
model audit timestamps. Explicit many-to-many values replace that relation;
omitting the relation preserves it. Unchanged payloads do not write model fields.
A stale model instance cannot overwrite unrelated columns during its update.

## Custom handlers and non-model serializers

```python
from common.update_utils import validate_partial_update

serializer = validate_partial_update(
    self.get_serializer, instance, request.data
)
self.perform_update(serializer)
```

Outside viewsets, supply the serializer class and context, then save:

```python
serializer = validate_partial_update(
    ItemSerializer, instance, request.data, context={"request": request}
)
instance = serializer.save()
```

The helper accepts a serializer factory, an existing model/object/mapping, and
JSON or multipart data. It validates without saving. Plain serializers can also
validate edits to JSON configuration; the handler then explicitly merges the
validated data. Pass `raise_exception=False` only when preserving a custom error
response, and check `serializer.is_valid()` before using its data or saving.

## Legacy services and output-only serializers

```python
from common.update_utils import validate_model_update

serializer = validate_model_update(
    instance, request.data, allowed_fields=["notes", "active", "owner_id"]
)
serializer.save(updated_by=request.user)
```

This builds an allowlisted model validator and delegates to the same partial
validation helper. It accepts foreign-key names, allowed `_id` aliases and
already-resolved model references. It validates before modifying the instance.
Use domain serializers when custom validation is needed; legacy services retain
their domain validation and authorization. `common.utils.update_model_fields`
and `update_model_fields_core` use this path, covering older APIViews and adapters.
For bulk updates, validate each existing record before saving any records, inside
the endpoint's transaction. List creation is not an implicit bulk-update API.

## Cross-field validation and domain behavior

Use `get_update_value(instance, attrs, "field")` when validation needs an omitted
field's stored value. This preserves explicit null/false/zero values without
adding stored fields to the write payload. Use model/source names after serializer
deserialization. Derived fields should only be recalculated when their inputs
change. Nested replacement objects must still enforce their own required fields.

The shared save layer does not replace business workflows. Audit metadata,
approval transitions, dependent calculations, journal reversals and cache
invalidation remain controlled by the existing resource services and save hooks.
Action endpoints still require their operation's target or command inputs.

Cash-transaction edits no longer require `transaction_type` when it is omitted.
Omitted `base_amount` (and transfer `to_amount`) is preserved; clients changing
those values must submit them explicitly. Creation still derives defaults.
The payment form already submits its converted amount. Editing cash transactions
retains their existing pending/approval and journal reversal workflow.

## Adoption and verification

The shared bases cover model resources in accounting, finance, academics,
students, grading, staff, HR, payroll, employee benefits, core tenant management,
users, authorization, notifications, backups and settings. Custom APIViews,
function-based onboarding updates, JSON branding, logo edits, bulk installments,
tuition and transcript updates also use the helper directly or via the legacy
adapter.

Regression coverage is in `common/tests/test_partial_updates.py`,
`common/tests/test_update_endpoint_regressions.py`,
`common/tests/partial_update_integration.py`, and
`accounting/test_partial_updates.py`. The isolated SQLite integration suite checks
actual persisted values and UPDATE columns, PUT/PATCH behavior, omitted required
fields, explicit null/false/zero, invalid input, readonly fields, multipart data,
relations, no-op requests and preservation of creation requirements.

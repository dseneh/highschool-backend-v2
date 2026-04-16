from django.db.models import Model
from rest_framework.response import Response


class AccountingErrorFormattingMixin:
    """Normalize API errors to a single detail object: {"detail": "..."}."""

    def _extract_detail(self, payload):
        if isinstance(payload, dict):
            if "detail" in payload:
                return payload.get("detail")

            # Pick first field error and flatten list payloads.
            first_key = next(iter(payload.keys()), None)
            if first_key is None:
                return "Request failed"

            first_value = payload[first_key]
            if isinstance(first_value, list):
                first_value = first_value[0] if first_value else "Request failed"
            return str(first_value)

        if isinstance(payload, list):
            return str(payload[0]) if payload else "Request failed"

        return str(payload)

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        if response is None:
            return response

        if response.status_code >= 400:
            detail = self._extract_detail(response.data)
            response.data = {"detail": detail}

        return response

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if getattr(response, "status_code", 200) >= 400:
            data = getattr(response, "data", None)
            if not (isinstance(data, dict) and "detail" in data):
                detail = self._extract_detail(data)
                response.data = {"detail": detail}
        return response

    def _normalize_for_compare(self, value):
        if isinstance(value, Model):
            return value.pk
        if isinstance(value, (list, tuple)):
            return [self._normalize_for_compare(item) for item in value]
        if isinstance(value, dict):
            return {key: self._normalize_for_compare(val) for key, val in value.items()}
        return value

    def _get_changed_fields(self, instance, validated_data):
        changed = {}
        for field_name, new_value in validated_data.items():
            current_value = getattr(instance, field_name, None)
            if self._normalize_for_compare(current_value) != self._normalize_for_compare(new_value):
                changed[field_name] = new_value
        return changed

    def update(self, request, *args, **kwargs):
        """
        Apply PATCH-like semantics for both PUT/PATCH and only persist changed fields.
        This allows clients to send single-field or partial updates across accounting APIs.
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        changed_fields = self._get_changed_fields(instance, serializer.validated_data)
        if changed_fields:
            updated_instance = serializer.update(instance, changed_fields)
        else:
            updated_instance = instance

        if getattr(updated_instance, "_prefetched_objects_cache", None):
            updated_instance._prefetched_objects_cache = {}

        response_serializer = self.get_serializer(updated_instance)
        return Response(response_serializer.data)

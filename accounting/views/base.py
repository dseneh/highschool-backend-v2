from common.viewsets import PartialUpdateMixin


class AccountingErrorFormattingMixin(PartialUpdateMixin):
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

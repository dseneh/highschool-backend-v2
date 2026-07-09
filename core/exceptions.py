"""Core API exceptions."""

from rest_framework.exceptions import APIException


class TenantAccessDenied(APIException):
    status_code = 423
    default_detail = "Workspace access is restricted."
    default_code = "TENANT_ACCESS_DENIED"

    def __init__(self, detail=None, code=None):
        super().__init__(detail, code)
        self.error_code = code or self.default_code

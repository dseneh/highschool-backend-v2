"""Authorization-related API exceptions."""

from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException

from authorization.services import NO_ASSIGNED_ROLE_CODE, NO_ASSIGNED_ROLE_DETAIL


class NoAssignedRole(APIException):
    """Raised before any credential is issued to a user without a role."""

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = NO_ASSIGNED_ROLE_DETAIL
    default_code = NO_ASSIGNED_ROLE_CODE
    error_code = NO_ASSIGNED_ROLE_CODE

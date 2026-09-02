import json

from django.conf import settings
from rest_framework.response import Response

from common.crypto import encrypt_text


def encrypt_data(payload) -> dict:
    """Encrypt a response payload with the shared versioned AES-GCM helper."""
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    return encrypt_text(payload)


def secure_response(data, status=200):
    """Encrypt selected responses in production when explicitly enabled."""
    if getattr(settings, "ENV", "development") == "production":
        return Response(encrypt_data(data), status=status)
    return Response(data, status=status)

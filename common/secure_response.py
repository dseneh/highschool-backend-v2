import base64
import json
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from rest_framework.response import Response
import logging

logger = logging.getLogger(__name__)

# Lazy loading of encryption key to avoid loading at module import time
_KEY = None
_AES = None

def _get_encryption_key():
    """Safely get and validate encryption key"""
    try:
        aes_key = getattr(settings, 'SECRET_AES_KEY', None)
        
        # If key is not set or is the default placeholder, generate a temporary one
        if not aes_key or aes_key == 'your-aes-secret-key-change-in-production':
            logger.warning("SECRET_AES_KEY not properly configured. Generating temporary key for development.")
            # Generate a random 32-byte (256-bit) key
            key = os.urandom(32)
            logger.info(f"Generated temporary AES key with 32 bytes (256 bits)")
            return key
        
        # Try to decode the key
        key = base64.b64decode(aes_key)
        
        # Validate key length (128, 192, or 256 bits = 16, 24, or 32 bytes)
        if len(key) not in [16, 24, 32]:
            logger.error(f"Invalid AES key length: {len(key)} bytes. Expected 16, 24, or 32 bytes.")
            raise ValueError(f"AES key must be 16, 24, or 32 bytes, got {len(key)}")
        
        logger.info(f"Successfully loaded AES key with {len(key)} bytes ({len(key)*8} bits)")
        return key
    except Exception as e:
        logger.warning(f"Failed to load encryption key: {e}. Generating temporary key.")
        # Generate a temporary key for development
        key = os.urandom(32)
        return key

def _get_aes():
    """Lazy load AES cipher"""
    global _KEY, _AES
    if _AES is None:
        _KEY = _get_encryption_key()
        _AES = AESGCM(_KEY)
    return _AES

def encrypt_data(payload: dict) -> dict:
    aes = _get_aes()
    iv = os.urandom(12)                # 12 bytes recommended for GCM
    plaintext = json.dumps(payload).encode("utf-8")
    ct = aes.encrypt(iv, plaintext, None)  # ciphertext||tag
    return {
        "iv": base64.b64encode(iv).decode("ascii"),
        "data": base64.b64encode(ct).decode("ascii"),
    }


def secure_response(data, status=200):
    """
    Automatically encrypt response if in production.
    """
    if getattr(settings, 'ENV', 'development') == "production":
        if not isinstance(data, str):
            data = json.dumps(data)
        encrypted = encrypt_data(data)
        return Response(encrypted, status=status)
    else:
        # In development or testing, return plain response
        return Response(data, status=status)

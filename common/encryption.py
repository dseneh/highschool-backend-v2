"""
Encryption configuration utilities for the application.
Handles AES key generation and validation.
"""
import os
import base64
import hashlib
import logging
from decouple import config

logger = logging.getLogger(__name__)


def generate_aes_key():
    """Generate a secure 32-byte AES key and return as base64 string"""
    return base64.b64encode(os.urandom(32)).decode('ascii')


def get_aes_key_from_secret(secret_key):
    """Generate a deterministic AES key from a secret key"""
    hash_input = f"{secret_key}-aes-encryption".encode('utf-8')
    key_bytes = hashlib.sha256(hash_input).digest()  # 32 bytes
    return base64.b64encode(key_bytes).decode('ascii')


def validate_and_fix_aes_key(key_b64):
    """
    Validate and fix AES key to ensure proper length.
    Returns a valid base64-encoded AES key.
    """
    try:
        decoded_key = base64.b64decode(key_b64)
        
        # If key is valid length (16, 24, or 32 bytes), use it
        if len(decoded_key) in [16, 24, 32]:
            logger.info(f"Using provided AES key with {len(decoded_key)} bytes")
            return key_b64
        
        # If invalid length, fix it
        if len(decoded_key) >= 32:
            # Truncate to 32 bytes for AES-256
            truncated_key = decoded_key[:32]
            fixed_key = base64.b64encode(truncated_key).decode('ascii')
            logger.warning(f"Truncated AES key from {len(decoded_key)} to 32 bytes")
            return fixed_key
        else:
            # Pad with zeros to reach 32 bytes
            padded_key = decoded_key + b'\x00' * (32 - len(decoded_key))
            fixed_key = base64.b64encode(padded_key).decode('ascii')
            logger.warning(f"Padded AES key from {len(decoded_key)} to 32 bytes")
            return fixed_key
            
    except Exception as e:
        logger.error(f"Failed to decode provided AES key: {e}")
        raise


def get_configured_aes_key(secret_key):
    """
    Get AES key from environment or generate a fallback.
    
    Args:
        secret_key: The Django SECRET_KEY to use for fallback generation
        
    Returns:
        str: Base64-encoded AES key suitable for encryption
    """
    try:
        # Try to get from environment
        env_key = config("SECRET_AES_KEY", default=None)
        
        if env_key:
            try:
                return validate_and_fix_aes_key(env_key)
            except Exception as e:
                logger.error(f"Environment AES key invalid, falling back: {e}")
        
        # Generate fallback key from SECRET_KEY
        fallback_key = get_aes_key_from_secret(secret_key)
        logger.info("Using fallback AES key generated from SECRET_KEY")
        return fallback_key
        
    except Exception as e:
        # Ultimate fallback
        logger.error(f"AES key configuration failed, using ultimate fallback: {e}")
        return get_aes_key_from_secret(secret_key)
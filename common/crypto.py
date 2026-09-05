"""Versioned authenticated encryption helpers.

New payloads use AES-GCM (v2). Historical unversioned envelopes remain
readable: 12-byte IVs are treated as AES-GCM nonces and 16-byte IVs as
legacy AES-CFB. New writes never use CFB.
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.decrepit.ciphers.modes import CFB
from django.conf import settings


V2 = 2


def _key() -> bytes:
    raw = base64.b64decode(settings.SECRET_AES_KEY, validate=True)
    if len(raw) not in (16, 24, 32):
        raise ValueError("SECRET_AES_KEY must decode to 16, 24, or 32 bytes")
    return raw


def encrypt_text(plaintext: str, *, associated_data: bytes | None = None) -> dict:
    nonce = os.urandom(12)
    encoded_nonce = base64.b64encode(nonce).decode("ascii")
    ciphertext = AESGCM(_key()).encrypt(nonce, plaintext.encode("utf-8"), associated_data)
    return {
        "v": V2,
        "alg": "AES-GCM",
        "nonce": encoded_nonce,
        # Compatibility alias for existing response decoders that call the
        # 12-byte GCM nonce an `iv`.
        "iv": encoded_nonce,
        "data": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_text(envelope: dict, *, associated_data: bytes | None = None) -> str:
    version = envelope.get("v")
    raw_nonce_or_iv = base64.b64decode(envelope.get("nonce") or envelope["iv"])
    ciphertext = base64.b64decode(envelope["data"])

    if version is not None and int(version) >= V2:
        plaintext = AESGCM(_key()).decrypt(raw_nonce_or_iv, ciphertext, associated_data)
        return plaintext.decode("utf-8")

    # Historical secure_response envelopes were unversioned AES-GCM and used
    # the field name `iv` for a 12-byte nonce.
    if version is None and len(raw_nonce_or_iv) == 12:
        plaintext = AESGCM(_key()).decrypt(raw_nonce_or_iv, ciphertext, associated_data)
        return plaintext.decode("utf-8")

    # Legacy AES-CFB envelope: 16-byte {iv, data}. Read-only compatibility.
    if len(raw_nonce_or_iv) != 16:
        raise ValueError("Unsupported encrypted envelope")
    cipher = Cipher(algorithms.AES(_key()), CFB(raw_nonce_or_iv))
    decryptor = cipher.decryptor()
    return (decryptor.update(ciphertext) + decryptor.finalize()).decode("utf-8")

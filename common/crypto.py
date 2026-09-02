"""Versioned authenticated encryption helpers.

New payloads use AES-GCM (v2). Legacy AES-CFB envelopes can still be
read so existing encrypted data can be migrated without a flag day.
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


V2 = 2


def _key() -> bytes:
    raw = base64.b64decode(settings.SECRET_AES_KEY, validate=True)
    if len(raw) not in (16, 24, 32):
        raise ValueError("SECRET_AES_KEY must decode to 16, 24, or 32 bytes")
    return raw


def encrypt_text(plaintext: str, *, associated_data: bytes | None = None) -> dict:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, plaintext.encode("utf-8"), associated_data)
    return {
        "v": V2,
        "alg": "AES-GCM",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "data": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_text(envelope: dict, *, associated_data: bytes | None = None) -> str:
    if int(envelope.get("v") or 1) >= V2:
        nonce = base64.b64decode(envelope["nonce"])
        ciphertext = base64.b64decode(envelope["data"])
        plaintext = AESGCM(_key()).decrypt(nonce, ciphertext, associated_data)
        return plaintext.decode("utf-8")

    # Legacy v1 AES-CFB envelope: {iv, data}. Read-only compatibility.
    iv = base64.b64decode(envelope["iv"])
    ciphertext = base64.b64decode(envelope["data"])
    cipher = Cipher(algorithms.AES(_key()), modes.CFB(iv))
    decryptor = cipher.decryptor()
    return (decryptor.update(ciphertext) + decryptor.finalize()).decode("utf-8")

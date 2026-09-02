"""Minimal RFC 6238 TOTP helpers with encrypted-at-rest secrets."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from common.crypto import decrypt_text, encrypt_text


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(padded, casefold=True)


def totp(secret: str, *, at_time: int | None = None, period: int = 30, digits: int = 6) -> str:
    counter = int((at_time if at_time is not None else time.time()) // period)
    digest = hmac.new(_decode_secret(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def verify_totp(secret: str, code: str, *, window: int = 1) -> bool:
    candidate = str(code or "").strip()
    if not (candidate.isdigit() and len(candidate) == 6):
        return False
    now = int(time.time())
    for step in range(-window, window + 1):
        if hmac.compare_digest(totp(secret, at_time=now + step * 30), candidate):
            return True
    return False


def encrypt_secret(secret: str, user_id) -> dict:
    return encrypt_text(secret, associated_data=f"mfa:{user_id}".encode())


def decrypt_secret(envelope: dict, user_id) -> str:
    return decrypt_text(envelope, associated_data=f"mfa:{user_id}".encode())


def provisioning_uri(secret: str, email: str, issuer: str = "EzySchool") -> str:
    label = quote(f"{issuer}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def generate_recovery_codes(count: int = 8) -> tuple[list[str], list[str]]:
    codes = [f"{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}" for _ in range(count)]
    return codes, [hash_recovery_code(code) for code in codes]

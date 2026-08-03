import base64
import hashlib
import hmac


def hash_value(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _base64url_sha256(raw: str) -> str:
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def timing_safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def verify_pkce_s256(code_verifier: str, expected_code_challenge: str) -> bool:
    computed = _base64url_sha256(code_verifier)
    return timing_safe_equal(computed, expected_code_challenge)

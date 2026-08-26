"""Privacy-preserving public school and account discovery services."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Q
from django_tenants.utils import get_public_schema_name, schema_context

from core.models import Tenant
from staff.models import Staff
from students.models import Student

CHALLENGE_TTL_SECONDS = 10 * 60
DISCOVERY_TTL_SECONDS = 5 * 60
MAX_VERIFY_ATTEMPTS = 5
GENERIC_MESSAGE = (
    "If we found an account matching that information, verification "
    "instructions have been sent to the contact information on file."
)


@dataclass(frozen=True)
class NormalizedIdentifier:
    kind: str
    value: str


def normalize_identifier(value: str, kind: str | None = None) -> NormalizedIdentifier:
    raw = (value or "").strip()
    detected = (kind or "").strip().lower()
    if not detected:
        if "@" in raw:
            detected = "email"
        elif re.fullmatch(r"[\d\s()+-]+", raw or "") and len(re.sub(r"\D", "", raw)) >= 7:
            detected = "phone"
        else:
            detected = "id_number"

    if detected == "email":
        normalized = raw.casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address.")
    elif detected == "phone":
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("0") and len(digits) in {9, 10}:
            digits = "231" + digits[1:]
        normalized = digits
        if len(normalized) < 7 or len(normalized) > 15:
            raise ValueError("Enter a valid phone number.")
    elif detected == "id_number":
        normalized = raw.upper()
        if not re.fullmatch(r"[A-Z0-9._-]{2,64}", normalized):
            raise ValueError("Enter a valid ID number.")
    else:
        raise ValueError("Unsupported identifier type.")
    return NormalizedIdentifier(detected, normalized)


def identifier_digest(identifier: NormalizedIdentifier) -> str:
    value = f"{identifier.kind}:{identifier.value}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), value, hashlib.sha256).hexdigest()


def request_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",", 1)[0] if forwarded else request.META.get("REMOTE_ADDR", "unknown")).strip()


def allow_request(scope: str, key: str, *, limit: int, window: int) -> bool:
    digest = hmac.new(settings.SECRET_KEY.encode(), key.encode(), hashlib.sha256).hexdigest()
    cache_key = f"account-discovery:rate:{scope}:{digest}"
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=window)
        count = 1
    return count <= limit


def public_school_results(query: str, location: str = "", limit: int = 20) -> list[dict]:
    query = (query or "").strip()
    if len(query) < 2:
        return []
    with schema_context(get_public_schema_name()):
        filters = (
            Q(name__icontains=query)
            | Q(short_name__icontains=query)
            | Q(id_number__iexact=query)
            | Q(emis_number__iexact=query)
        )
        if location:
            filters &= Q(city__icontains=location) | Q(state__icontains=location) | Q(country__icontains=location)
        tenants = (
            Tenant.objects.filter(filters, active=True)
            .exclude(schema_name=get_public_schema_name())
            .exclude(status="deleted")
            .only("name", "short_name", "schema_name", "city", "state", "country", "logo")
            .order_by("name")[:limit]
        )
        return [
            {
                "name": tenant.name,
                "short_name": tenant.short_name,
                "workspace": tenant.schema_name,
                "city": tenant.city,
                "state": tenant.state,
                "country": tenant.country,
                "logo": tenant.logo.url if tenant.logo else None,
            }
            for tenant in tenants
        ]


def _tenant_summary(tenant: Tenant, user_type: str, record) -> dict:
    return {
        "workspace": tenant.schema_name,
        "school_name": tenant.name,
        "school_logo": tenant.logo.url if tenant.logo else None,
        "user_type": user_type,
        "id_number": getattr(record, "id_number", None),
    }


def find_accounts(identifier: NormalizedIdentifier) -> tuple[list[dict], set[str]]:
    """Resolve matches internally; this data is never returned before verification."""
    accounts: list[dict] = []
    destinations: set[str] = set()
    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        tenants = list(
            Tenant.objects.filter(active=True)
            .exclude(schema_name=public_schema)
            .exclude(status="deleted")
            .only("name", "schema_name", "logo")
        )
        if identifier.kind in {"email", "id_number"}:
            user_filter = (
                Q(email__iexact=identifier.value)
                if identifier.kind == "email"
                else Q(id_number__iexact=identifier.value)
            )
            for user in get_user_model().objects.filter(user_filter, is_active=True).only("id", "id_number", "email")[:10]:
                email = (user.email or "").strip().casefold()
                if email:
                    destinations.add(email)
                if user.is_superuser:
                    accounts.append(
                        {
                            "workspace": "admin",
                            "school_name": "EzySchool Administration",
                            "school_logo": None,
                            "user_type": "administrator",
                            "id_number": user.id_number,
                        }
                    )
                try:
                    from tenant_users.permissions.models import UserTenantPermissions

                    for tenant in tenants:
                        with schema_context(tenant.schema_name):
                            if UserTenantPermissions.objects.filter(profile_id=user.id).exists():
                                accounts.append(_tenant_summary(tenant, "user", user))
                except Exception:
                    # Tenant source records below remain the fallback for older workspaces.
                    pass

    for tenant in tenants:
        with schema_context(tenant.schema_name):
            if identifier.kind == "email":
                model_filter = Q(email__iexact=identifier.value)
            elif identifier.kind == "phone":
                model_filter = Q(phone_number__icontains=identifier.value[-7:])
            else:
                model_filter = Q(id_number__iexact=identifier.value)
            for user_type, model in (("student", Student), ("staff", Staff)):
                for record in model.objects.filter(model_filter).only("id_number", "email")[:10]:
                    accounts.append(_tenant_summary(tenant, user_type, record))
                    email = (getattr(record, "email", "") or "").strip().casefold()
                    if email:
                        destinations.add(email)

    unique = {(item["workspace"], item["user_type"], item["id_number"]): item for item in accounts}
    return list(unique.values()), destinations


def create_challenge(identifier: NormalizedIdentifier) -> str:
    challenge_id = secrets.token_urlsafe(32)
    identifier_key = f"account-discovery:identifier:{identifier_digest(identifier)}"
    previous_challenge = cache.get(identifier_key)
    if previous_challenge:
        cache.delete(f"account-discovery:challenge:{previous_challenge}")
    accounts, destinations = find_accounts(identifier)
    code = f"{secrets.randbelow(1_000_000):06d}"
    cache.set(
        f"account-discovery:challenge:{challenge_id}",
        {
            "code_hash": hashlib.sha256(f"{challenge_id}:{code}".encode()).hexdigest(),
            "accounts": accounts,
            "attempts": 0,
        },
        timeout=CHALLENGE_TTL_SECONDS,
    )
    cache.set(identifier_key, challenge_id, timeout=CHALLENGE_TTL_SECONDS)
    if accounts and destinations:
        from common.email_service import send_account_discovery_code_email

        for destination in destinations:
            send_account_discovery_code_email(destination, code)
    return challenge_id


def verify_challenge(challenge_id: str, code: str) -> tuple[str, list[dict]] | None:
    key = f"account-discovery:challenge:{challenge_id}"
    payload = cache.get(key)
    if not payload or payload.get("attempts", 0) >= MAX_VERIFY_ATTEMPTS:
        return None
    expected = payload.get("code_hash", "")
    supplied = hashlib.sha256(f"{challenge_id}:{code}".encode()).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        payload["attempts"] = payload.get("attempts", 0) + 1
        cache.set(key, payload, timeout=CHALLENGE_TTL_SECONDS)
        return None
    cache.delete(key)
    discovery_token = secrets.token_urlsafe(32)
    accounts = payload.get("accounts", [])
    cache.set(
        f"account-discovery:verified:{discovery_token}",
        {"accounts": accounts},
        timeout=DISCOVERY_TTL_SECONDS,
    )
    return discovery_token, accounts

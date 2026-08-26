"""Public school directory helpers for the marketing website."""

import hashlib

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django_tenants.utils import get_public_schema_name, schema_context

from core.models import Tenant


def allow_school_search(request, *, limit: int = 60, window: int = 60) -> bool:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = (
        forwarded.split(",", 1)[0]
        if forwarded
        else request.META.get("REMOTE_ADDR", "unknown")
    ).strip()
    digest = hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()
    key = f"public-school-search:{digest}"
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window)
        count = 1
    return count <= limit


def public_school_results(query: str, location: str = "", limit: int = 20) -> list[dict]:
    """Return only active schools and fields approved for public discovery."""
    query = (query or "").strip()
    location = (location or "").strip()
    if len(query) < 2:
        return []

    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        filters = (
            Q(name__icontains=query)
            | Q(short_name__icontains=query)
            | Q(id_number__iexact=query)
            | Q(emis_number__iexact=query)
        )
        if location:
            filters &= (
                Q(city__icontains=location)
                | Q(state__icontains=location)
                | Q(country__icontains=location)
            )

        schools = (
            Tenant.objects.filter(filters, active=True)
            .exclude(schema_name=public_schema)
            .exclude(status="deleted")
            .only(
                "name",
                "short_name",
                "schema_name",
                "city",
                "state",
                "country",
                "logo",
            )
            .order_by("name")[:limit]
        )
        return [
            {
                "name": school.name,
                "short_name": school.short_name,
                "workspace": school.schema_name,
                "city": school.city,
                "state": school.state,
                "country": school.country,
                "logo": school.logo.url if school.logo else None,
            }
            for school in schools
        ]

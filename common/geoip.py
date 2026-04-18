"""
Lightweight GeoIP resolver using MaxMind's GeoLite2-City database.

Falls back gracefully (returns ``None``) when the database file is missing
or an IP cannot be resolved.  This keeps audit logging functional even
before the operator downloads the free GeoLite2 database.

Usage::

    from common.geoip import resolve_location
    loc = resolve_location("8.8.8.8")   # {"city": "Mountain View", "country": "US", ...}
    loc = resolve_location("127.0.0.1") # None  (private / unresolvable)
"""

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# Path to the GeoLite2-City.mmdb file.
# Override with ``GEOIP_PATH`` in Django settings.
_DB_PATH: Path = getattr(
    settings,
    "GEOIP_PATH",
    Path(settings.BASE_DIR) / "geoip" / "GeoLite2-City.mmdb",
)

_reader = None
_db_checked = False
_UNSET = object()
_external_ip = _UNSET


def _get_reader():
    """Lazy-initialise the MaxMind database reader (singleton)."""
    global _reader, _db_checked  # noqa: PLW0603
    if _db_checked:
        return _reader
    _db_checked = True
    db = Path(_DB_PATH)
    if not db.is_file():
        logger.info(
            "GeoLite2-City database not found at %s – location data will be unavailable. "
            "Run  python manage.py download_geoip_db  to fetch it.",
            db,
        )
        return None
    try:
        import geoip2.database

        _reader = geoip2.database.Reader(str(db))
        logger.info("GeoIP reader initialised from %s", db)
    except Exception as exc:
        logger.warning("Failed to open GeoIP database: %s", exc)
    return _reader


def resolve_location(ip_address: str) -> dict | None:
    """
    Resolve *ip_address* to a location dict.

    Returns a dict like::

        {"city": "Cape Town", "country": "ZA", "latitude": -33.93, "longitude": 18.46}

    …or ``None`` when resolution is impossible.
    """
    if not ip_address:
        return None
    reader = _get_reader()
    if reader is None:
        return None

    # In local dev, loopback addresses can't be resolved – look up the
    # machine's external IP instead so the feature is testable.
    lookup_ip = ip_address
    if ip_address in ("127.0.0.1", "::1", "0.0.0.0") and settings.DEBUG:
        lookup_ip = _get_external_ip() or ip_address

    try:
        resp = reader.city(lookup_ip)
        return {
            "city": resp.city.name or "",
            "country": resp.country.iso_code or "",
            "latitude": resp.location.latitude,
            "longitude": resp.location.longitude,
        }
    except Exception:
        # Private IPs, unknown addresses, etc.
        return None


def _get_external_ip() -> str | None:
    """Best-effort fetch of this machine's public IP (cached)."""
    global _external_ip  # noqa: PLW0603
    if _external_ip is not _UNSET:
        return _external_ip
    try:
        import urllib.request

        _external_ip = (
            urllib.request.urlopen("https://api.ipify.org", timeout=3)  # noqa: S310
            .read()
            .decode()
            .strip()
        )
    except Exception:
        _external_ip = None
    return _external_ip

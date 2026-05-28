"""School / employer header payload for payroll payslips and exports."""

from __future__ import annotations

from typing import Any

from common.services.pdf_components import format_tenant_address, resolve_tenant_school
from core.serializers import TenantSerializer


def build_payroll_school_header(request=None) -> dict[str, Any] | None:
    """
    Build canonical school header fields for payroll payslips (web + export).
    Reuses TenantSerializer so logo/contact fields match GET /tenants/{schema}/.
    """
    school = resolve_tenant_school()
    if not school:
        return None

    tenant_data = TenantSerializer(school, context={"request": request}).data
    logo = tenant_data.get("logo") or None
    address_line = format_tenant_address(school) or tenant_data.get("full_address") or None
    phone = (tenant_data.get("phone") or "").strip() or None
    email = (tenant_data.get("email") or "").strip() or None
    contact_parts = [part for part in (phone, email) if part]

    return {
        "name": (tenant_data.get("name") or "").strip(),
        "logo": logo,
        "logo_url": logo,
        "id_number": (tenant_data.get("id_number") or "").strip() or None,
        "workspace": (tenant_data.get("workspace") or tenant_data.get("schema_name") or "").strip() or None,
        "emis_number": (tenant_data.get("emis_number") or "").strip() or None,
        "address_line": address_line,
        "phone": phone,
        "email": email,
        "website": (tenant_data.get("website") or "").strip() or None,
        "contact_line": " · ".join(contact_parts) if contact_parts else None,
        "slogan": (tenant_data.get("slogan") or "").strip() or None,
    }

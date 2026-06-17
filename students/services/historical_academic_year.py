"""Create and resolve historical academic years for transcript grade mapping."""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from django.db import transaction

from academics.models import AcademicYear


def normalize_academic_year_name(label: str) -> str:
    label = (label or "").strip()
    if not label:
        return label
    match = re.match(r"^(\d{4})\s*[-/]\s*(\d{4})$", label)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return label


def _parse_year_bounds(name: str) -> tuple[Optional[date], Optional[date]]:
    match = re.match(r"^(\d{4})-(\d{4})$", name or "")
    if not match:
        return None, None
    start_year = int(match.group(1))
    end_year = int(match.group(2))
    return date(start_year, 8, 1), date(end_year, 6, 30)


@transaction.atomic
def resolve_academic_year_for_historical_grade(
    *,
    year_label: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    create_historical_if_missing: bool = True,
) -> Optional[AcademicYear]:
    normalized = normalize_academic_year_name(year_label)
    if not normalized:
        return None

    for year_type in (AcademicYear.YearType.REGULAR, AcademicYear.YearType.HISTORICAL):
        existing = AcademicYear.objects.filter(
            name__iexact=normalized,
            year_type=year_type,
        ).first()
        if existing:
            return existing

    if not create_historical_if_missing:
        return None

    inferred_start, inferred_end = _parse_year_bounds(normalized)
    return AcademicYear.objects.create(
        name=normalized,
        year_type=AcademicYear.YearType.HISTORICAL,
        start_date=start_date or inferred_start,
        end_date=end_date or inferred_end,
        status="inactive",
        current=False,
    )

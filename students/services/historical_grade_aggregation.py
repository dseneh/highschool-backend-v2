"""Merge verified historical transcript grades into ranking and honor roll calculations."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable
from uuid import UUID

from students.models.historical_grade import HistoricalGradeRecord


def get_flagged_historical_subject_averages(
    student_ids: Iterable[UUID | str],
    *,
    academic_year_id: str | None = None,
    for_rankings: bool = False,
    for_honor_roll: bool = False,
) -> dict[str, list[Decimal]]:
    """
    Return {student_id: [historical final percentages]} for verified historical
    grade records with the relevant inclusion flag set.
    """
    if not student_ids or (not for_rankings and not for_honor_roll):
        return {}

    qs = HistoricalGradeRecord.objects.filter(
        student_id__in=list(student_ids),
        status=HistoricalGradeRecord.Status.VERIFIED,
        final_percentage__isnull=False,
    )

    if for_rankings:
        qs = qs.filter(include_in_rankings=True)
    else:
        qs = qs.filter(include_in_honor_roll=True)

    if academic_year_id:
        qs = qs.filter(academic_year_id=academic_year_id)

    result: dict[str, list[Decimal]] = defaultdict(list)
    for record in qs:
        result[str(record.student_id)].append(record.final_percentage)

    return result

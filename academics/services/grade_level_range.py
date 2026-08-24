from __future__ import annotations

import uuid

from django.db.models import Max, QuerySet

from academics.models import GradeLevel
from core.models import Division


def default_divisions_in_order() -> list[Division]:
    from defaults.data.division_list import division_list

    divisions = []
    for item in division_list:
        expected_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"ezyschool:division:{item['name'].lower()}",
        )
        division = Division.objects.filter(pk=expected_id).first()
        if division is None:
            division = Division.objects.filter(name__iexact=item["name"]).first()
        if division is None:
            raise ValueError(f"Shared division '{item['name']}' is not configured.")
        divisions.append(division)
    return divisions


def default_max_level_for_division(division: Division) -> int | None:
    from defaults.data.division_list import division_list
    from defaults.data.gade_level import grade_level_data

    division_index = next(
        (index for index, item in enumerate(default_divisions_in_order()) if item.id == division.id),
        None,
    )
    if division_index is None:
        division_index = next(
            (
                index
                for index, item in enumerate(division_list)
                if item["name"].casefold() == division.name.casefold()
            ),
            None,
        )
    if division_index is None:
        return None

    levels = [
        item["level"]
        for item in grade_level_data
        if item.get("division") == division_index
    ]
    return max(levels, default=None)


def max_level_for_division(division: Division | None) -> int | None:
    if division is None:
        return None

    configured_max = GradeLevel.objects.filter(
        division=division,
    ).aggregate(max_level=Max("level"))["max_level"]
    return configured_max or default_max_level_for_division(division)


def grade_levels_through_division(
    queryset: QuerySet,
    division: Division | None,
) -> QuerySet:
    max_level = max_level_for_division(division)
    if max_level is None:
        return queryset.none() if division is not None else queryset
    return queryset.filter(level__lte=max_level)


def default_grade_levels_through_division(division: Division | None) -> list[dict]:
    from defaults.data.gade_level import grade_level_data

    max_level = default_max_level_for_division(division) if division else None
    if max_level is None:
        return [] if division is not None else list(grade_level_data)
    return [item for item in grade_level_data if item["level"] <= max_level]

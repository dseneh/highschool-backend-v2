"""Single source of truth for which academic year is current."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from academics.models import AcademicYear


def clear_current_academic_years(*, exclude_id=None) -> int:
    """Unset `current` on every academic year except the optional exclusion."""
    queryset = AcademicYear.objects.filter(current=True)
    if exclude_id:
        queryset = queryset.exclude(id=exclude_id)
    return queryset.update(current=False)


@transaction.atomic
def set_current_academic_year(academic_year: AcademicYear, *, actor=None):
    """Promote an academic year to current, demoting any other current year.

    Returns `(academic_year, previous_current)`.
    """
    if academic_year.year_type != AcademicYear.YearType.REGULAR:
        raise ValidationError(
            "Historical academic years cannot be set as the current academic year."
        )
    if not academic_year.start_date or not academic_year.end_date:
        raise ValidationError(
            "Set the start and end dates before making this the current academic year."
        )

    previous = (
        AcademicYear.objects.select_for_update()
        .filter(current=True)
        .exclude(id=academic_year.id)
        .first()
    )
    clear_current_academic_years(exclude_id=academic_year.id)

    academic_year.current = True
    # A current year is by definition the one in use, so it cannot stay inactive/onhold.
    academic_year.status = "active"
    if getattr(actor, "is_authenticated", False):
        academic_year.updated_by = actor
    academic_year.save(update_fields=["current", "status", "updated_by", "updated_at"])

    return academic_year, previous

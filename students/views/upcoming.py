"""
GET /students/upcoming/

Returns upcoming school calendar events and birthdays (students + staff)
for the next N days (default 14). Used by the dashboard General tab.
"""

from datetime import date, timedelta

from django.db.models import Q
from django.db.models.functions import ExtractDay, ExtractMonth
from rest_framework.response import Response
from rest_framework.views import APIView

from ..access_policies import StudentAccessPolicy


def _birthday_q(today: date, days: int) -> Q:
    """Build a Q filter matching rows whose (month, day) of date_of_birth
    falls within the next ``days`` calendar days starting from today."""
    q = Q()
    for offset in range(days + 1):
        d = today + timedelta(days=offset)
        q |= Q(bday_month=d.month, bday_day=d.day)
    return q


def _days_until_birthday(dob: date, today: date) -> int:
    """How many days until the next occurrence of this birthday."""
    this_year = today.year
    try:
        candidate = dob.replace(year=this_year)
    except ValueError:
        # Feb 29 → treat as Feb 28 in non-leap years
        candidate = dob.replace(year=this_year, day=28)
    if candidate < today:
        try:
            candidate = dob.replace(year=this_year + 1)
        except ValueError:
            candidate = dob.replace(year=this_year + 1, day=28)
    return (candidate - today).days


class DashboardUpcomingView(APIView):
    """
    GET /students/upcoming/?days=14

    Response:
    {
        "events": [
            { "id", "name", "event_type", "date", "all_day" }
        ],
        "student_birthdays": [
            { "id", "full_name", "id_number", "date_of_birth", "days_away", "grade_level" }
        ],
        "staff_birthdays": [
            { "id", "full_name", "role", "date_of_birth", "days_away" }
        ]
    }
    """

    permission_classes = [StudentAccessPolicy]

    def get(self, request):
        try:
            days = max(1, min(int(request.query_params.get("days", 14)), 60))
        except (ValueError, TypeError):
            days = 14

        today = date.today()
        end_date = today + timedelta(days=days)

        events = self._get_events(today, end_date)
        student_birthdays = self._get_student_birthdays(today, days)
        staff_birthdays = self._get_staff_birthdays(today, days)

        return Response(
            {
                "events": events,
                "student_birthdays": student_birthdays,
                "staff_birthdays": staff_birthdays,
            }
        )

    # ------------------------------------------------------------------ events

    def _get_events(self, today: date, end_date: date):
        from academics.models import SchoolCalendarEventOccurrence

        occurrences = (
            SchoolCalendarEventOccurrence.objects.filter(
                occurrence_date__gte=today,
                occurrence_date__lte=end_date,
            )
            .select_related("event")
            .order_by("occurrence_date", "event__name")
        )

        # De-duplicate: show the *earliest* occurrence of each event only
        seen: set = set()
        result = []
        for occ in occurrences:
            if occ.event_id in seen:
                continue
            seen.add(occ.event_id)
            result.append(
                {
                    "id": str(occ.event.id),
                    "name": occ.event.name,
                    "event_type": occ.event.event_type,
                    "date": occ.occurrence_date.isoformat(),
                    "all_day": occ.event.all_day,
                }
            )

        return result

    # --------------------------------------------------------------- birthdays

    def _get_student_birthdays(self, today: date, days: int):
        from students.models import Student

        try:
            qs = list(
                Student.objects.filter(date_of_birth__isnull=False)
                .annotate(
                    bday_month=ExtractMonth("date_of_birth"),
                    bday_day=ExtractDay("date_of_birth"),
                )
                .filter(_birthday_q(today, days))
                .values(
                    "id",
                    "first_name",
                    "last_name",
                    "id_number",
                    "date_of_birth",
                )[:30]
            )
        except Exception:
            return []

        # Resolve current grade level via latest active enrollment
        enrollment_map: dict = {}
        try:
            student_ids = [str(row["id"]) for row in qs]
            from students.models import Enrollment
            enrollments = Enrollment.objects.filter(
                student_id__in=student_ids,
                academic_year__current=True,
            ).select_related("grade_level").values("student_id", "grade_level__short_name", "grade_level__name")
            for e in enrollments:
                sid = str(e["student_id"])
                enrollment_map[sid] = e.get("grade_level__short_name") or e.get("grade_level__name") or ""
        except Exception:
            pass

        result = []
        for row in qs:
            sid = str(row["id"])
            dob: date = row["date_of_birth"]
            result.append(
                {
                    "id": sid,
                    "full_name": f"{row['first_name']} {row['last_name']}".strip(),
                    "id_number": row["id_number"] or "",
                    "date_of_birth": dob.isoformat(),
                    "days_away": _days_until_birthday(dob, today),
                    "grade_level": enrollment_map.get(sid, ""),
                }
            )

        result.sort(key=lambda r: r["days_away"])
        return result

    def _get_staff_birthdays(self, today: date, days: int):
        from hr.models import Employee

        try:
            qs = (
                Employee.objects.filter(date_of_birth__isnull=False)
                .annotate(
                    bday_month=ExtractMonth("date_of_birth"),
                    bday_day=ExtractDay("date_of_birth"),
                )
                .filter(_birthday_q(today, days))
                .values("id", "first_name", "last_name", "date_of_birth", "job_title", "position__title")
                [:30]
            )
        except Exception:
            return []

        result = []
        for row in qs:
            dob: date = row["date_of_birth"]
            role = row.get("job_title") or row.get("position__title") or ""
            result.append(
                {
                    "id": str(row["id"]),
                    "full_name": f"{row['first_name']} {row['last_name']}".strip(),
                    "role": role,
                    "date_of_birth": dob.isoformat(),
                    "days_away": _days_until_birthday(dob, today),
                }
            )

        result.sort(key=lambda r: r["days_away"])
        return result

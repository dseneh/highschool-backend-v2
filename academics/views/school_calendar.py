from datetime import date, timedelta

from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from ..access_policies import AcademicsAccessPolicy
from ..models import AcademicYear, SchoolCalendarEvent, SchoolCalendarEventOccurrence, SchoolCalendarSettings
from ..serializers import SchoolCalendarEventSerializer, SchoolCalendarSettingsSerializer, SectionScheduleSerializer
from business.core.adapters import get_section_by_id, get_section_schedules


class SchoolCalendarSettingsView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get(self, request):
        settings = SchoolCalendarSettings.get_solo()
        serializer = SchoolCalendarSettingsSerializer(settings, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        settings = SchoolCalendarSettings.get_solo()
        serializer = SchoolCalendarSettingsSerializer(
            settings,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SchoolCalendarEventListView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def _parse_date(self, value: str | None):
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError({"detail": "Invalid date format. Use YYYY-MM-DD."}) from exc

    def _validate_school_year_bounds(self, start_date: date | None, end_date: date | None):
        if not start_date or not end_date:
            return

        current_year = AcademicYear.get_current_academic_year()
        if not current_year:
            return

        if start_date < current_year.start_date or end_date > current_year.end_date:
            raise ValidationError(
                {
                    "detail": (
                        "Date range must be within the current school year "
                        f"({current_year.start_date.isoformat()} to {current_year.end_date.isoformat()})."
                    )
                }
            )

    def _get_queryset(self, request):
        queryset = SchoolCalendarEvent.objects.filter(active=True).prefetch_related("sections")
        start_date = self._parse_date(request.query_params.get("start"))
        end_date = self._parse_date(request.query_params.get("end"))

        self._validate_school_year_bounds(start_date, end_date)

        if not start_date or not end_date:
            return queryset.order_by("start_date", "name")

        event_ids = (
            SchoolCalendarEventOccurrence.objects.filter(
                occurrence_date__gte=start_date,
                occurrence_date__lte=end_date,
                event__active=True,
            )
            .values_list("event_id", flat=True)
            .distinct()
        )

        return queryset.filter(id__in=event_ids).order_by("start_date", "name")

    def get(self, request):
        events = self._get_queryset(request)
        serializer = SchoolCalendarEventSerializer(events, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = SchoolCalendarEventSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        event = serializer.save(created_by=request.user, updated_by=request.user)
        return Response(
            SchoolCalendarEventSerializer(event, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class SchoolCalendarEventDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get_object(self, event_id):
        try:
            return SchoolCalendarEvent.objects.prefetch_related("sections").get(id=event_id)
        except SchoolCalendarEvent.DoesNotExist as exc:
            raise NotFound("School calendar event does not exist with this id") from exc

    def get(self, request, id):
        event = self.get_object(id)
        serializer = SchoolCalendarEventSerializer(event, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        event = self.get_object(id)
        serializer = SchoolCalendarEventSerializer(
            event,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        event = self.get_object(id)
        event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SectionCalendarProjectionView(APIView):
    """Project section calendar data by combining schedule slots and school events for a date range."""

    permission_classes = [AcademicsAccessPolicy]

    def _parse_date(self, value: str | None):
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError({"detail": "Invalid date format. Use YYYY-MM-DD."}) from exc

    def _validate_school_year_bounds(self, start_date: date, end_date: date):
        current_year = AcademicYear.get_current_academic_year()
        if not current_year:
            return

        if start_date < current_year.start_date or end_date > current_year.end_date:
            raise ValidationError(
                {
                    "detail": (
                        "Date range must be within the current school year "
                        f"({current_year.start_date.isoformat()} to {current_year.end_date.isoformat()})."
                    )
                }
            )

    def _iter_dates(self, start_date: date, end_date: date):
        current = start_date
        while current <= end_date:
            yield current
            current += timedelta(days=1)

    def get(self, request, section_id):
        section = get_section_by_id(section_id)
        if not section:
            raise NotFound("Section does not exist with this id")

        start_date = self._parse_date(request.query_params.get("start"))
        end_date = self._parse_date(request.query_params.get("end"))

        if not start_date or not end_date:
            raise ValidationError({"detail": "Both start and end query params are required (YYYY-MM-DD)."})

        if start_date > end_date:
            raise ValidationError({"detail": "start date must be on or before end date."})

        self._validate_school_year_bounds(start_date, end_date)

        settings = SchoolCalendarSettings.get_solo()
        operating_days = settings.operating_days or [1, 2, 3, 4, 5]

        schedules = get_section_schedules(section)
        serialized_schedules = SectionScheduleSerializer(schedules, many=True, context={"request": request}).data
        schedules_by_day: dict[int, list] = {}
        for item in serialized_schedules:
            period_time = item.get("period_time") or {}
            day_of_week = period_time.get("day_of_week")
            if not day_of_week:
                continue
            schedules_by_day.setdefault(day_of_week, []).append(item)

        events_qs = (
            SchoolCalendarEvent.objects.filter(active=True)
            .filter(Q(applies_to_all_sections=True) | Q(sections=section))
            .prefetch_related("sections")
            .distinct()
            .order_by("start_date", "name")
        )
        serialized_events = SchoolCalendarEventSerializer(events_qs, many=True, context={"request": request}).data
        serialized_events_by_id = {str(event["id"]): event for event in serialized_events}

        occurrence_rows = (
            SchoolCalendarEventOccurrence.objects.filter(
                occurrence_date__gte=start_date,
                occurrence_date__lte=end_date,
                event__in=events_qs,
            )
            .select_related("event")
            .order_by("occurrence_date", "event__start_date", "event__name")
        )
        event_ids_by_date: dict[str, list[str]] = {}
        for row in occurrence_rows:
            key = row.occurrence_date.isoformat()
            event_ids_by_date.setdefault(key, []).append(str(row.event_id))

        days = []
        for target_date in self._iter_dates(start_date, end_date):
            day_of_week = target_date.isoweekday()
            event_ids = event_ids_by_date.get(target_date.isoformat(), [])
            events_for_day = [
                serialized_events_by_id[event_id]
                for event_id in event_ids
                if event_id in serialized_events_by_id
            ]

            is_blocked = any(
                event["event_type"] in ("holiday", "non_school_day")
                for event in events_for_day
            )
            is_operating_day = day_of_week in operating_days

            days.append(
                {
                    "date": target_date.isoformat(),
                    "day_of_week": day_of_week,
                    "is_operating_day": is_operating_day,
                    "is_blocked_by_event": is_blocked,
                    "events": events_for_day,
                    "schedules": [] if (is_blocked or not is_operating_day) else schedules_by_day.get(day_of_week, []),
                }
            )

        return Response(
            {
                "section": {
                    "id": str(section.id),
                    "name": section.name,
                },
                "range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
                "operating_days": operating_days,
                "days": days,
            },
            status=status.HTTP_200_OK,
        )
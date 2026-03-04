from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy

from common.utils import update_model_fields

from ..serializers import SectionScheduleSerializer
from business.core.services import (
    validate_section_schedule_creation,
    validate_period_time_belongs_to_period,
    check_section_schedule_exists
)
from business.core.adapters import (
    get_section_by_id,
    get_section_schedules,
    get_subject_by_id,
    get_period_by_id_or_name,
    get_period_time_by_id,
    create_section_schedule_in_db
)

class SectionScheduleListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [AllowAny]
    def get_object(self, id):
        section = get_section_by_id(id)
        if not section:
            raise NotFound("Section does not exist with this id")
        return section

    def get(self, request, section_id):
        section = self.get_object(section_id)

        schedules = get_section_schedules(section)
        serializer = SectionScheduleSerializer(schedules, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, section_id):
        section = self.get_object(section_id)
        req_data: dict = request.data

        subject_id = req_data.get("subject")
        period_id = req_data.get("period")
        period_time_id = req_data.get("period_time")

        # Validate schedule creation
        is_valid, error = validate_section_schedule_creation(
            subject_id, period_id, period_time_id, section_id
        )
        if not is_valid:
            return Response({"detail": error}, status=400)

        subject = get_subject_by_id(subject_id)
        if not subject:
            return Response({"detail": "Subject does not exist"}, status=400)

        period = get_period_by_id_or_name(period_id)
        if not period:
            return Response({"detail": "Period does not exist"}, status=400)

        period_time = get_period_time_by_id(period_time_id)
        if not period_time:
            return Response({"detail": "Period time does not exist"}, status=400)

        # Validate period time belongs to period
        is_valid, error = validate_period_time_belongs_to_period(
            period_time.period.id, period.id
        )
        if not is_valid:
            return Response({"detail": error}, status=400)

        # Check if schedule already exists
        if check_section_schedule_exists(section, subject_id, period_id, period_time_id):
            return Response({"detail": "Section schedule already exists"}, status=400)

        data = {
            "section": section,
            "subject": subject,
            "period": period,
            "period_time": period_time,
        }

        try:
            class_schedule = create_section_schedule_in_db(data)
            serializer = SectionScheduleSerializer(class_schedule)
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

from business.core.adapters import get_section_schedule_by_id, delete_section_schedule_from_db

class SectionScheduleDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        section_schedule = get_section_schedule_by_id(id)
        if not section_schedule:
            raise NotFound("Section schedule does not exist with this id")
        return section_schedule

    def get(self, request, id):
        section_schedule = self.get_object(id)
        serializer = SectionScheduleSerializer(section_schedule)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        period = self.get_object(id)

        allowed_fields = [
            # "section",
            "subject",
            "period",
            "period_time",
        ]

        serializer = update_model_fields(
            request, period, allowed_fields, SectionScheduleSerializer
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        period = self.get_object(id)
        delete_section_schedule_from_db(period)
        return Response(status=status.HTTP_204_NO_CONTENT)

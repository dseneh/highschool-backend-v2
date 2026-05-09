from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
import logging
from ..access_policies import AcademicsAccessPolicy

from ..serializers import SectionScheduleSerializer
from ..services import sync_schedule_projections_for_class_schedule
from business.core.adapters import (
    get_section_by_id,
    get_section_schedules,
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
        payload = request.data.copy()
        payload["section"] = str(section.id)

        serializer = SectionScheduleSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        class_schedule = serializer.save(created_by=request.user, updated_by=request.user)
        # Ensure projections are synchronized even if signal delivery is skipped.
        sync_schedule_projections_for_class_schedule(class_schedule)
        return Response(
            SectionScheduleSerializer(class_schedule, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

from business.core.adapters import get_section_schedule_by_id, delete_section_schedule_from_db

logger = logging.getLogger(__name__)

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
        section_schedule = self.get_object(id)
        serializer = SectionScheduleSerializer(
            section_schedule,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        class_schedule = serializer.save(updated_by=request.user)
        sync_schedule_projections_for_class_schedule(class_schedule)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        schedule = self.get_object(id)
        deleted = delete_section_schedule_from_db(schedule)
        if deleted:
            return Response(status=status.HTTP_204_NO_CONTENT)

        logger.warning("Failed to delete section schedule %s", id)
        return Response(
            {"detail": "Failed to delete schedule entry."},
            status=status.HTTP_400_BAD_REQUEST,
        )

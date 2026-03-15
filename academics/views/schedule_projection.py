from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.access_policies import AcademicsAccessPolicy
from academics.models import GradeBookScheduleProjection, StudentScheduleProjection
from academics.serializers import (
    GradeBookScheduleProjectionSerializer,
    StudentScheduleProjectionSerializer,
    TeacherScheduleProjectionSerializer,
)
from staff.models import TeacherSchedule


class TeacherScheduleProjectionListView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get(self, request, teacher_id):
        queryset = (
            TeacherSchedule.objects.select_related(
                "teacher",
                "class_schedule",
                "class_schedule__section",
                "class_schedule__period",
                "class_schedule__period_time",
                "class_schedule__section_time_slot",
                "class_schedule__subject",
                "class_schedule__subject__subject",
            )
            .filter(teacher_id=teacher_id, active=True, class_schedule__active=True)
            .order_by("class_schedule__section_time_slot__day_of_week", "class_schedule__section_time_slot__start_time")
        )

        day_of_week = request.query_params.get("day_of_week")
        if day_of_week:
            queryset = queryset.filter(class_schedule__section_time_slot__day_of_week=day_of_week)

        serializer = TeacherScheduleProjectionSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GradeBookScheduleProjectionListView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get(self, request, gradebook_id):
        queryset = (
            GradeBookScheduleProjection.objects.select_related(
                "class_schedule",
                "gradebook",
                "gradebook__academic_year",
                "section",
                "section_subject",
                "section_subject__subject",
                "subject",
                "period",
            )
            .filter(gradebook_id=gradebook_id, active=True, class_schedule__active=True)
            .order_by("day_of_week", "start_time")
        )

        day_of_week = request.query_params.get("day_of_week")
        if day_of_week:
            queryset = queryset.filter(day_of_week=day_of_week)

        serializer = GradeBookScheduleProjectionSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class StudentScheduleProjectionListView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get(self, request, student_id):
        queryset = (
            StudentScheduleProjection.objects.select_related(
                "class_schedule",
                "enrollment",
                "enrollment__academic_year",
                "student",
                "section",
                "section_subject",
                "section_subject__subject",
                "subject",
                "period",
            )
            .filter(student_id=student_id, active=True, class_schedule__active=True)
            .order_by("day_of_week", "start_time")
        )

        academic_year_id = request.query_params.get("academic_year_id")
        if academic_year_id:
            queryset = queryset.filter(enrollment__academic_year_id=academic_year_id)

        day_of_week = request.query_params.get("day_of_week")
        if day_of_week:
            queryset = queryset.filter(day_of_week=day_of_week)

        serializer = StudentScheduleProjectionSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

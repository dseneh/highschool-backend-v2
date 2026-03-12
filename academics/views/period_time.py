from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy

from common.utils import update_model_fields

from ..serializers import PeriodTimeSerializer
from business.core.services import validate_period_time_creation
from business.core.adapters import (
    get_period_by_id_or_name, get_period_times_for_period, 
    create_period_time_in_db
)

class PeriodTimeListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [AllowAny]
    def get_period_object(self, id):
        period = get_period_by_id_or_name(id)
        if not period:
            raise NotFound("Period does not exist with this id")
        return period

    def get(self, request, period_id):
        period = self.get_period_object(period_id)

        period_times = get_period_times_for_period(period)
        serializer = PeriodTimeSerializer(
            period_times, many=True, context={"request": request}
        )

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, period_id):
        period = self.get_period_object(period_id)
        req_data: dict = request.data

        start_time = req_data.get("start_time")
        end_time = req_data.get("end_time")
        day_of_week = req_data.get("day_of_week")

        # Validate period time creation
        is_valid, error = validate_period_time_creation(start_time, end_time, day_of_week, period_id)
        if not is_valid:
            return Response({"detail": error}, status=400)

        data = {
            "start_time": start_time,
            "end_time": end_time,
            "day_of_week": day_of_week,
        }

        try:
            period_time = create_period_time_in_db(period, data, request.user)
            serializer = PeriodTimeSerializer(period_time)
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

from business.core.adapters import get_period_time_by_id, update_period_time_in_db, delete_period_time_from_db

class PeriodTimeDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        period_time = get_period_time_by_id(id)
        if not period_time:
            raise NotFound("PeriodTime does not exist with this id")
        return period_time

    def get(self, request, id):
        period_time = self.get_object(id)
        serializer = PeriodTimeSerializer(period_time)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        period_time = self.get_object(id)

        allowed_fields = [
            "start_time",
            "end_time",
            "day_of_week",
            "active",
        ]

        serializer = update_model_fields(
            request, period_time, allowed_fields, PeriodTimeSerializer
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        period_time = self.get_object(id)
        delete_period_time_from_db(period_time)
        return Response(status=status.HTTP_204_NO_CONTENT)

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy

from common.utils import update_model_fields

from ..serializers import PeriodSerializer
from business.core.services import validate_period_creation, validate_period_name_uniqueness
from business.core.adapters import get_school_periods, get_period_names_for_school, create_period_in_db

class PeriodListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [AllowAny]

    def get(self, request):
        periods = get_school_periods()
        serializer = PeriodSerializer(periods, many=True, context={"request": request})

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        req_data: dict = request.data

        name = req_data.get("name")

        # Validate period creation
        is_valid, error = validate_period_creation(name)
        if not is_valid:
            return Response({"detail": error}, status=400)

        # Check name uniqueness
        existing_names = get_period_names_for_school()
        is_unique, error = validate_period_name_uniqueness(name, existing_names)
        if not is_unique:
            return Response({"detail": error}, status=400)

        data = {
            "name": name,
            "description": req_data.get("description"),
            "period_type": req_data.get("period_type") or "class",
        }

        try:
            period = create_period_in_db(data, request.user)
            serializer = PeriodSerializer(period)
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

from business.core.adapters import get_period_by_id_or_name, delete_period_from_db

class PeriodDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        period = get_period_by_id_or_name(id)
        if not period:
            raise NotFound("Period does not exist with this id")
        return period

    def get(self, request, id):
        period = self.get_object(id)
        serializer = PeriodSerializer(period)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        period = self.get_object(id)

        allowed_fields = [
            "name",
            "description",
            "period_type",
            "active",
        ]

        serializer = update_model_fields(
            request, period, allowed_fields, PeriodSerializer
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        period = self.get_object(id)
        delete_period_from_db(period)
        return Response(status=status.HTTP_204_NO_CONTENT)

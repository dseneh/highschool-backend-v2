from datetime import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy

from common.utils import get_object_by_uuid_or_fields, update_model_fields

from ..models import AcademicYear, MarkingPeriod, Semester
from ..serializers import MarkingPeriodSerializer

# Business logic imports
from business.core.services import marking_period_service
from business.core.adapters import marking_period_adapter

class MarkingPeriodListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [AllowAny]
    def get_semester_year_object(self, id):
        return get_object_by_uuid_or_fields(Semester, id, fields=["name"])

    def get(self, request, semester_id):
        semester = self.get_semester_year_object(semester_id)

        marking_period = semester.marking_periods.all()
        serializer = MarkingPeriodSerializer(
            marking_period, many=True, context={"request": request}
        )

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, semester_id):
        semester = self.get_semester_year_object(semester_id)
        req_data: dict = request.data

        # Validate using business logic
        validation_result = marking_period_service.validate_marking_period_creation(
            name=req_data.get("name"),
            start_date=req_data.get("start_date"),
            end_date=req_data.get("end_date"),
            short_name=req_data.get("short_name"),
            description=req_data.get("description")
        )

        if not validation_result["valid"]:
            return Response({"detail": validation_result["error"]}, status=400)

        # Validate dates are within semester
        if semester.start_date and semester.end_date:
            dates_result = marking_period_service.validate_marking_period_dates_in_semester(
                start_date=validation_result["data"]["start_date"],
                end_date=validation_result["data"]["end_date"],
                semester_start_date=semester.start_date,
                semester_end_date=semester.end_date
            )

            if not dates_result["valid"]:
                return Response({"detail": dates_result["error"]}, status=400)

        try:
            marking_period = marking_period_adapter.create_marking_period_in_db(
                data=validation_result["data"],
                semester_id=str(semester.id),
                user=request.user
            )
            serializer = MarkingPeriodSerializer(marking_period, context={"request": request})
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

class MarkingPeriodDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        try:
            f = Q(id=id) | Q(name=id)
            return MarkingPeriod.objects.get(f)
        except MarkingPeriod.DoesNotExist:
            raise NotFound("marking_period does not exist with this id")

    def get(self, request, id):
        marking_period = self.get_object(id)
        serializer = MarkingPeriodSerializer(marking_period)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        marking_period = self.get_object(id)

        allowed_fields = [
            "name",
            "start_date",
            "end_date",
            "active",
            "short_name",
        ]

        # convert string dates to date objects for comparison
        start_date = request.data.get("start_date", str(marking_period.start_date))
        end_date = request.data.get("end_date", str(marking_period.end_date))
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "Invalid date format. Use YYYY-MM-DD format"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.data["start_date"] = start_date_obj
        request.data["end_date"] = end_date_obj

        serializer = update_model_fields(
            request, marking_period, allowed_fields, MarkingPeriodSerializer
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        marking_period = self.get_object(id)

        if marking_period.grade_books.all():
            marking_period.active = False
            marking_period.save()
            return Response(
                {
                    "detail": "Cannot delete marking period with associated grade books, please delete those grade books first. Marking period has been deactivated."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        marking_period.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class MarkingPeriodListAllView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get(self, request):
        academic_year_id = (
            request.query_params.get("academic_year")
            or request.query_params.get("academic_year_id")
        )
        if not academic_year_id:
            return Response(
                {"detail": "academic_year query param is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if academic_year_id == "current":
            academic_year = AcademicYear.get_current_academic_year()
        else:
            try:
                academic_year = AcademicYear.objects.filter(pk=academic_year_id).first()
            except (DjangoValidationError, TypeError, ValueError):
                academic_year = None

        if not academic_year:
            return Response(
                {"detail": "The requested academic year does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        marking_periods = MarkingPeriod.objects.filter(
            semester__academic_year=academic_year
        ).select_related("semester", "semester__academic_year")
        serializer = MarkingPeriodSerializer(marking_periods, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

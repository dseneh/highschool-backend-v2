
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..access_policies import AcademicsAccessPolicy
from common.cache_service import DataCache

from ..models import AcademicYear
from ..serializers import AcademicYearSerializer

# Business logic imports
from business.core.services import academic_year_service
from business.core.adapters import academic_year_adapter


def _force_delete_instance(instance, visited: set[tuple[str, str, str]]) -> None:
    """Recursively delete objects blocked by PROTECT constraints."""
    if not instance or getattr(instance, "pk", None) is None:
        return

    key = (
        instance._meta.app_label,
        instance._meta.model_name,
        str(instance.pk),
    )
    if key in visited:
        return
    visited.add(key)

    try:
        instance.delete()
    except ProtectedError as exc:
        for protected in list(exc.protected_objects):
            _force_delete_instance(protected, visited)
        instance.delete()

class AcademicYearListView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get(self, request):        
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        include_historical = request.query_params.get('include_historical', 'false').lower() == 'true'
        include_inactive = request.query_params.get('include_inactive', 'false').lower() == 'true'
        academic_years = DataCache.get_academic_years(force_refresh)
        
        filtered = academic_years
        if not include_inactive:
            filtered = [year for year in filtered if year.get('status') == 'active']
        if not include_historical:
            filtered = [
                year for year in filtered
                if year.get('year_type', 'regular') == 'regular'
            ]
        
        return Response(filtered)

    def post(self, request):
        req_data: dict = request.data
        year_type = req_data.get("year_type", "regular")

        if year_type == "historical":
            existing_names = list(
                AcademicYear.objects.exclude(name__isnull=True)
                .exclude(name="")
                .values_list("name", flat=True)
            )
            validation_result = academic_year_service.validate_historical_academic_year_creation(
                name=req_data.get("name"),
                start_date=req_data.get("start_date"),
                end_date=req_data.get("end_date"),
                existing_names=existing_names,
            )
            if not validation_result["valid"]:
                return Response({"detail": validation_result["error"]}, status=400)
            try:
                academic_year = academic_year_adapter.create_academic_year_in_db(
                    data=validation_result["data"],
                    user=request.user,
                )
                serializer = AcademicYearSerializer(
                    academic_year, context={"request": request}
                )
                return Response(serializer.data, status=201)
            except Exception as e:
                return Response({"detail": str(e)}, status=400)

        # Validate using business logic
        validation_result = academic_year_service.validate_academic_year_creation(
            start_date=req_data.get("start_date"),
            end_date=req_data.get("end_date"),
            name=req_data.get("name")
        )
        
        if not validation_result["valid"]:
            return Response({"detail": validation_result["error"]}, status=400)
        
        # Check date overlap using business logic
        existing_years = academic_year_adapter.get_existing_academic_years()
        
        overlap_result = academic_year_service.check_academic_year_overlap(
            start_date=validation_result["data"]["start_date"],
            end_date=validation_result["data"]["end_date"],
            existing_years=existing_years
        )
        
        if overlap_result["has_overlap"]:
            return Response({"detail": overlap_result["error"]}, status=400)
        
        # Generate name if not provided
        if not validation_result["data"].get("name"):
            validation_result["data"]["name"] = academic_year_service.generate_academic_year_name(
                validation_result["data"]["start_date"],
                validation_result["data"]["end_date"]
            )
        
        # Add current flag
        validation_result["data"]["current"] = req_data.get("current", False)

        try:
            academic_year = academic_year_adapter.create_academic_year_in_db(
                data=validation_result["data"],
                user=request.user
            )
            serializer = AcademicYearSerializer(
                academic_year, context={"request": request}
            )
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

class AcademicYearDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    def get_object(self, id):
        # try:
        f = Q(id=id) | Q(name=id)
        # return AcademicYear.objects.get(f)
        return get_object_or_404(AcademicYear, f)
        # except AcademicYear.DoesNotExist:
        #     raise NotFound("Academic year does not exist with this id")

    def get(self, request, id):
        academic_year = self.get_object(id)
        include_stats = request.query_params.get('include_stats', 'false').lower() == 'true'
        serializer = AcademicYearSerializer(
            academic_year,
            context={"request": request, "include_stats": include_stats}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        academic_year = self.get_object(id)

        update_data = {}
        
        # Handle name update
        name = request.data.get("name")
        if name:
            if AcademicYear.objects.filter(name__iexact=name).exists():
                return Response(
                    {"detail": f"Academic year named '{name}' already exists"},
                    status=400,
                )
            update_data["name"] = name
        
        # Handle current flag update
        current = request.data.get("current", False)
        if current and not academic_year.current:
            update_data["current"] = True

        # Handle date updates
        s = str(academic_year.start_date)
        e = str(academic_year.end_date)
        start_date = request.data.get("start_date", s)
        end_date = request.data.get("end_date", e)

        if start_date != s or end_date != e:
            # Validate using business logic
            validation_result = academic_year_service.validate_academic_year_creation(
                start_date=start_date,
                end_date=end_date,
                name=name
            )
            
            if not validation_result["valid"]:
                return Response({"detail": validation_result["error"]}, status=400)
            
            # Check overlap using business logic
            existing_years = academic_year_adapter.get_existing_academic_years(
                exclude_id=str(academic_year.id)
            )
            
            overlap_result = academic_year_service.check_academic_year_overlap(
                start_date=validation_result["data"]["start_date"],
                end_date=validation_result["data"]["end_date"],
                existing_years=existing_years
            )
            
            if overlap_result["has_overlap"]:
                return Response({"detail": overlap_result["error"]}, status=400)
            
            update_data["start_date"] = validation_result["data"]["start_date"]
            update_data["end_date"] = validation_result["data"]["end_date"]
        
        # Handle status update
        status_value = request.data.get("status")
        if status_value:
            update_data["status"] = status_value

        # Update in database
        updated_year = academic_year_adapter.update_academic_year_in_db(
            year_id=str(academic_year.id),
            data=update_data,
            user=request.user
        )
        
        if not updated_year:
            return Response({"detail": "Academic year not found"}, status=404)
        
        serializer = AcademicYearSerializer(updated_year, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        academic_year = self.get_object(id)
        if academic_year.current:
            return Response(
                {"detail": "Cannot delete current academic year."}, status=400
            )

        force = request.query_params.get("force", "false").lower() == "true"

        try:
            if not force:
                academic_year.delete()
                return Response(status=status.HTTP_204_NO_CONTENT)

            with transaction.atomic():
                _force_delete_instance(academic_year, visited=set())

            return Response(status=status.HTTP_204_NO_CONTENT)
        except ProtectedError as exc:
            return Response(
                {
                    "detail": "Academic year has related data and cannot be deleted without force.",
                    "can_force_delete": True,
                    "protected_count": len(exc.protected_objects),
                },
                status=400,
            )


class AcademicYearDeleteImpactView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get_object(self, id):
        f = Q(id=id) | Q(name=id)
        return get_object_or_404(AcademicYear, f)

    def get(self, request, id):
        academic_year = self.get_object(id)

        from accounting.models import AccountingFeeRate, AccountingStudentBill
        from finance.models import PaymentInstallment, Transaction
        from grading.models import Grade, GradeBook
        from students.models import Enrollment, StudentEnrollmentBill

        semester_count = academic_year.semesters.count()
        marking_period_count = academic_year.marking_periods.count()
        enrollment_count = Enrollment.objects.filter(academic_year=academic_year).count()
        gradebook_count = GradeBook.objects.filter(academic_year=academic_year).count()
        grade_count = Grade.objects.filter(academic_year=academic_year).count()
        installment_count = PaymentInstallment.objects.filter(academic_year=academic_year).count()
        transaction_count = Transaction.objects.filter(academic_year=academic_year).count()
        student_bill_count = StudentEnrollmentBill.objects.filter(
            enrollment__academic_year=academic_year
        ).count()
        accounting_bill_count = AccountingStudentBill.objects.filter(
            academic_year=academic_year
        ).count()
        accounting_fee_rates_count = AccountingFeeRate.objects.filter(
            academic_year=academic_year
        ).count()

        has_related_data = any(
            value > 0
            for value in [
                semester_count,
                marking_period_count,
                enrollment_count,
                gradebook_count,
                grade_count,
                installment_count,
                transaction_count,
                student_bill_count,
                accounting_bill_count,
                accounting_fee_rates_count,
            ]
        )

        reason = None
        if academic_year.current:
            reason = "Cannot delete current academic year."
        elif has_related_data:
            reason = "Academic year has related data. Use force delete to proceed."

        return Response(
            {
                "academic_year": {
                    "id": str(academic_year.id),
                    "name": academic_year.name,
                    "current": academic_year.current,
                    "status": academic_year.status,
                },
                "can_delete_without_force": (not academic_year.current) and (not has_related_data),
                "can_force_delete": not academic_year.current,
                "reason": reason,
                "counts": {
                    "semesters": semester_count,
                    "marking_periods": marking_period_count,
                    "enrollments": enrollment_count,
                    "gradebooks": gradebook_count,
                    "grades": grade_count,
                    "payment_installments": installment_count,
                    "transactions": transaction_count,
                    "student_bills": student_bill_count,
                    "accounting_student_bills": accounting_bill_count,
                    "accounting_fee_rates": accounting_fee_rates_count,
                },
            },
            status=status.HTTP_200_OK,
        )

# create an endpoint to get the current academic year for an institution
class CurrentAcademicYearView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get(self, request):
        from academics.serializers import AcademicYearSerializer
        from academics.models import AcademicYear

        # Check if stats are requested
        include_stats = request.query_params.get('include_stats', 'false').lower() == 'true'
        
        # Get the current academic year object
        academic_year = AcademicYear.objects.filter(current=True).first()
        
        if not academic_year:
            return Response(
                {"detail": "No current academic year found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        # Serialize with appropriate context
        serializer = AcademicYearSerializer(
            academic_year,
            context={"request": request, "include_stats": include_stats}
        )
        
        return Response(serializer.data, status=status.HTTP_200_OK)

from decimal import Decimal

from django.db.models import Avg, Count, Sum
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import StudentAccessPolicy

from academics.models import AcademicYear
from accounting.models import (
    AccountingConcession,
    AccountingCurrency,
    AccountingStudentBill,
    AccountingStudentBillLine,
)
from accounting.services.student_billing import sync_accounting_bill_concession_totals
from common.utils import get_object_by_uuid_or_fields
from students.models import Student
from students.serializers.concession import StudentConcessionSerializer


def _to_decimal(value):
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _calculate_concession_amount(student, academic_year, concession_type, target, value):
    tuition_amount = _to_decimal(
        AccountingStudentBillLine.objects.filter(
            student_bill__student=student,
            student_bill__academic_year=academic_year,
            fee_item__category="tuition",
        ).aggregate(total=Sum("line_amount"))["total"]
    )
    gross_amount = _to_decimal(
        AccountingStudentBillLine.objects.filter(
            student_bill__student=student,
            student_bill__academic_year=academic_year,
        ).aggregate(total=Sum("line_amount"))["total"]
    )
    other_fees_amount = max(Decimal("0"), gross_amount - tuition_amount)

    if target == AccountingConcession.ConcessionTarget.TUITION:
        base_amount = tuition_amount
    elif target == AccountingConcession.ConcessionTarget.OTHER_FEES:
        base_amount = other_fees_amount
    else:
        base_amount = gross_amount

    if base_amount <= 0:
        return Decimal("0")

    concession_value = _to_decimal(value)
    if concession_value <= 0:
        return Decimal("0")

    if concession_type == AccountingConcession.ConcessionType.PERCENTAGE:
        computed_amount = (base_amount * concession_value) / Decimal("100")
    else:
        computed_amount = concession_value

    return min(base_amount, computed_amount).quantize(Decimal("0.01"))


class StudentConcessionListCreateView(APIView):
    permission_classes = [StudentAccessPolicy]
    """List and create concessions for a student."""
    @staticmethod
    def _resolve_currency():
        currency = AccountingCurrency.objects.filter(is_base_currency=True, is_active=True).first()
        if currency is None:
            currency = AccountingCurrency.objects.filter(is_active=True).order_by("-is_base_currency", "code").first()
        return currency


    def _get_student(self, student_id):
        return get_object_by_uuid_or_fields(
            Student,
            student_id,
            fields=["id_number", "prev_id_number"],
        )

    def get(self, request, academic_year_id='current'):
        student_id = request.query_params.get("student_id")
        if student_id:
            try:
                student = self._get_student(student_id)
            except Student.DoesNotExist:
                return Response({"detail": "Student not found"}, status=status.HTTP_404_NOT_FOUND)

        # academic_year_id = request.query_params.get("academic_year_id")
        active = request.query_params.get("active")

        queryset = AccountingConcession.objects.select_related(
            "student", "academic_year"
        )
        if student_id:
            queryset = queryset.filter(student_id=student.id)

        if not academic_year_id or academic_year_id == "current":
            queryset = queryset.filter(academic_year__current=True)
        elif academic_year_id:
            queryset = queryset.filter(academic_year_id=academic_year_id)

        if active is not None:
            queryset = queryset.filter(is_active=str(active).lower() in ["true", "1", "yes"])

        serializer = StudentConcessionSerializer(queryset.order_by("-created_at"), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, academic_year_id='current'):
        student_id = request.data.get("student")
        if not student_id:
            return Response({"detail": "student_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            student = self._get_student(student_id)
        except Student.DoesNotExist:
            return Response({"detail": "Student not found"}, status=status.HTTP_404_NOT_FOUND)

        payload = request.data.copy()
        academic_year_id = payload.get("academic_year") or payload.get("academic_year_id")

        if academic_year_id == "current" or not academic_year_id:
            academic_year = AcademicYear.objects.filter(current=True).first() or AcademicYear.objects.filter(active=True).first()
        else:
            academic_year = AcademicYear.objects.filter(id=academic_year_id).first()

        if not academic_year:
            return Response(
                {"detail": "Academic year not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        currency = self._resolve_currency()
        if currency is None:
            return Response(
                {"detail": "No active accounting currency configured"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        concession_type = payload.get("concession_type")
        target = payload.get("target", AccountingConcession.ConcessionTarget.ENTIRE_BILL)
        value = payload.get("value")

        payload["academic_year"] = str(academic_year.id)
        payload["target"] = target
        computed_amount = _calculate_concession_amount(
            student=student,
            academic_year=academic_year,
            concession_type=concession_type,
            target=target,
            value=value,
        )

        student_bill = AccountingStudentBill.objects.filter(
            student=student,
            academic_year=academic_year,
        ).order_by("bill_date", "created_at").first()
        if student_bill:
            payload["student_bill"] = str(student_bill.id)

        serializer = StudentConcessionSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            student=student,
            student_bill=student_bill,
            currency=currency,
            computed_amount=computed_amount,
            created_by=request.user,
            updated_by=request.user,
        )

        sync_accounting_bill_concession_totals(student=student, academic_year=academic_year)

        return Response(serializer.data, status=status.HTTP_201_CREATED)


class StudentConcessionDetailView(APIView):
    permission_classes = [StudentAccessPolicy]
    """Retrieve, update, or soft-disable a concession."""

    def _get_concession(self, id):
        return AccountingConcession.objects.select_related("student", "academic_year").filter(id=id).first()

    def get(self, request, id):
        concession = self._get_concession(id)
        if not concession:
            return Response({"detail": "Concession not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = StudentConcessionSerializer(concession)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        concession = self._get_concession(id)
        if not concession:
            return Response({"detail": "Concession not found"}, status=status.HTTP_404_NOT_FOUND)

        payload = request.data.copy()
        serializer = StudentConcessionSerializer(concession, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_concession = serializer.save(updated_by=request.user)

        computed_amount = _calculate_concession_amount(
            student=updated_concession.student,
            academic_year=updated_concession.academic_year,
            concession_type=updated_concession.concession_type,
            target=updated_concession.target,
            value=updated_concession.value,
        )
        updated_concession.computed_amount = computed_amount
        updated_concession.save(update_fields=["computed_amount", "updated_at"])

        sync_accounting_bill_concession_totals(
            student=updated_concession.student,
            academic_year=updated_concession.academic_year,
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        concession = self._get_concession(id)
        if not concession:
            return Response({"detail": "Concession not found"}, status=status.HTTP_404_NOT_FOUND)

        # concession.active = False
        # concession.updated_by = request.user
        student = concession.student
        academic_year = concession.academic_year
        concession.delete()

        sync_accounting_bill_concession_totals(student=student, academic_year=academic_year)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentConcessionStatsView(APIView):
    permission_classes = [StudentAccessPolicy]
    """Get concession statistics."""

    def get(self, request, academic_year_id='current'):
        # Filter by academic year
        queryset = AccountingConcession.objects.select_related("student", "academic_year")
        
        if not academic_year_id or academic_year_id == "current":
            queryset = queryset.filter(academic_year__current=True)
        elif academic_year_id:
            queryset = queryset.filter(academic_year_id=academic_year_id)

        queryset = queryset.filter(is_active=True)

        # Total concessions
        total_concessions = queryset.count()

        # Total students with concessions (distinct)
        total_students = queryset.values('student').distinct().count()

        # Concessions by type
        by_type = queryset.values('concession_type').annotate(
            count=Count('id')
        ).order_by('-count')

        # Concessions by target
        by_target = queryset.values('target').annotate(
            count=Count('id')
        ).order_by('-count')

        # Total amount of concessions (sum of all calculated amounts)
        total_amount = queryset.aggregate(total=Sum('computed_amount'))['total'] or 0

        # Average concession amount
        avg_amount = queryset.aggregate(avg=Avg('computed_amount'))['avg'] or 0

        stats = {
            "total_concessions": total_concessions,
            "total_students": total_students,
            "total_amount": float(total_amount),
            "average_amount": float(avg_amount),
            "by_type": list(by_type),
            "by_target": list(by_target),
        }

        return Response(stats, status=status.HTTP_200_OK)

from rest_framework import serializers

from common.utils import get_enrollment_bill_summary

from ..models import StudentEnrollmentBill


class StudentBillSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentEnrollmentBill
        fields = [
            "id",
            "enrollment",
            "name",
            "amount",
            "type",
            "notes",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["enrollment"] = {
            "id": instance.enrollment.id,
            "student": {
                "id_number": instance.enrollment.student.id_number,
                "full_name": instance.enrollment.student.get_full_name(),
            },
            "academic_year": instance.enrollment.academic_year.name,
            "grade_level": instance.enrollment.grade_level.name,
            "section": instance.enrollment.section.name,
        }

        # Add billing summary
        # billing_summary = get_enrollment_bill_summary(instance.enrollment)
        # response["billing_summary"] = billing_summary

        return response


class StudentBillDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentEnrollmentBill
        fields = [
            "id",
            "enrollment",
            "name",
            "amount",
            "type",
            "notes",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["enrollment"] = {
            "id": instance.enrollment.id,
            "student": {
                "id_number": instance.enrollment.student.id_number,
                "full_name": instance.enrollment.student.get_full_name(),
            },
            "academic_year": instance.enrollment.academic_year.name,
            "grade_level": instance.enrollment.grade_level.name,
            "section": instance.enrollment.section.name,
        }

        # Add billing summary
        billing_summary = get_enrollment_bill_summary(
            instance.enrollment, 
            include_payment_plan=True, 
            include_payment_status=True
            )
        response["billing_summary"] = billing_summary

        return response

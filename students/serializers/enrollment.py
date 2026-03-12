from rest_framework import serializers

from common.utils import get_enrollment_bill_summary

from ..models import Enrollment


class EnrollmentListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Enrollment
        depth = 1
        fields = [
            "id",
            "student",
            "academic_year",
            "section",
            "status",
            "date_enrolled",
            "enrolled_as",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["student"] = instance.student.id_number
        response["section"] = {
            "id": instance.section.id,
            "name": instance.section.name,
        }
        response["grade_level"] = {
            "id": instance.section.grade_level.id,
            "name": instance.section.grade_level.name,
        }
        next_grade_level = instance.next_grade_level
        if next_grade_level:
            response["next_grade_level"] = {
                "id": next_grade_level.id,
                "name": next_grade_level.name,
            }
        response["academic_year"] = {
            "id": instance.academic_year.id,
            "name": instance.academic_year.name,
            "start_date": instance.academic_year.start_date,
            "end_date": instance.academic_year.end_date,
            "current": instance.academic_year.current,
        }

        # Get include_payment_plan and include_payment_status from context
        # Can be passed directly in context for reusability, or via request query params for backward compatibility
        context = self.context
        include_billing = context.get("include_billing", True)
        include_payment_plan = context.get("include_payment_plan", True)
        include_payment_status = context.get("include_payment_status", True)

        if include_billing:
            response["billing_summary"] = get_enrollment_bill_summary(
                instance,
                include_payment_plan=include_payment_plan,
                include_payment_status=include_payment_status,
            )
        return response


class EnrollmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Enrollment
        fields = [
            "id",
            "student",
            "academic_year",
            "section",
            "status",
            "date_enrolled",
            "notes",
            "meta",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["student"] = instance.student.id_number
        response["full_name"] = instance.student.get_full_name()
        response["section"] = instance.section.name
        response["grade_level"] = {
            "id": instance.section.grade_level.id,
            "name": instance.section.grade_level.name,
        }
        response["academic_year"] = instance.academic_year.name
        return response

from rest_framework import serializers

from common.utils import get_enrollment_bill_summary

from accounting.models import AccountingStudentBillLine


class StudentBillSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    enrollment = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()

    def get_enrollment(self, instance: AccountingStudentBillLine):
        enrollment = instance.student_bill.enrollment
        section = getattr(enrollment, "section", None)
        return {
            "id": enrollment.id,
            "student": {
                "id_number": enrollment.student.id_number,
                "full_name": enrollment.student.get_full_name(),
            },
            "academic_year": enrollment.academic_year.name,
            "grade_level": enrollment.grade_level.name,
            "section": section.name if section else None,
        }

    def get_name(self, instance: AccountingStudentBillLine):
        return instance.fee_item.name

    def get_amount(self, instance: AccountingStudentBillLine):
        return float(instance.line_amount)

    def get_type(self, instance: AccountingStudentBillLine):
        return instance.fee_item.category

    def get_notes(self, instance: AccountingStudentBillLine):
        return instance.description or None


class StudentBillDetailSerializer(StudentBillSerializer):
    billing_summary = serializers.SerializerMethodField()

    def get_billing_summary(self, instance: AccountingStudentBillLine):
        return get_enrollment_bill_summary(
            instance.student_bill.enrollment,
            include_payment_plan=True,
            include_payment_status=True,
        )

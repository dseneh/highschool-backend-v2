from types import SimpleNamespace

from django.core.mail import send_mail
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounting.models import AccountingStudentBill
from business.students.adapters import create_student_in_db, get_next_student_sequence
from business.students.services import student_service
from core.models import Tenant
from students.models import StudentGuardian
from students.views.utils import create_enrollment_for_student

from .enums import ApplicationStatus, ApplicationType
from .models import AdmissionApplication, ApplicationConversion, ApplicationPlacement
from .services import transition_application


class ApplicationConversionError(Exception):
    pass


def _guardian_names(profile):
    first_name = str(profile.get("first_name") or "").strip()
    last_name = str(profile.get("last_name") or "").strip()
    if not first_name and not last_name:
        parts = str(profile.get("name") or "").strip().split(maxsplit=1)
        first_name = parts[0] if parts else "Guardian"
        last_name = parts[1] if len(parts) > 1 else ""
    return first_name, last_name


def _create_student(application, placement, actor):
    tenant = Tenant.objects.filter(schema_name=connection.schema_name).first()
    if tenant is None:
        raise ApplicationConversionError("Tenant context could not be resolved.")
    profile = application.student_profile
    date_of_birth = parse_date(str(profile.get("date_of_birth") or ""))
    if date_of_birth is None:
        raise ApplicationConversionError("Student date of birth is invalid.")
    school_code = int(str(tenant.id_number)[-1]) if tenant.id_number else 1
    data = student_service.prepare_student_data_for_creation(
        {
            **profile,
            "date_of_birth": date_of_birth,
            "email": profile.get("email") or application.applicant_email,
            "phone_number": profile.get("phone_number") or application.applicant_phone,
            "entry_as": placement.enrolled_as,
        },
        school_code,
        get_next_student_sequence(),
    )
    data["grade_level"] = placement.grade_level
    student = create_student_in_db(data, created_by=actor, updated_by=actor)
    valid_relationships = {value for value, _label in StudentGuardian.RELATIONSHIP_CHOICES}
    for index, guardian_profile in enumerate(application.guardian_profiles):
        first_name, last_name = _guardian_names(guardian_profile)
        relationship = guardian_profile.get("relationship") or "other"
        if relationship not in valid_relationships:
            relationship = "other"
        StudentGuardian.objects.create(
            student=student,
            first_name=first_name,
            last_name=last_name,
            relationship=relationship,
            phone_number=guardian_profile.get("phone") or guardian_profile.get("phone_number"),
            email=guardian_profile.get("email"),
            address=guardian_profile.get("address"),
            occupation=guardian_profile.get("occupation"),
            workplace=guardian_profile.get("workplace"),
            is_primary=index == 0,
            created_by=actor,
            updated_by=actor,
        )
    return student


@transaction.atomic
def convert_application_to_enrollment(*, application, actor):
    locked = (
        AdmissionApplication.objects.select_for_update()
        .select_related("returning_student", "placement__academic_year", "placement__grade_level", "placement__section")
        .get(pk=application.pk)
    )
    existing = ApplicationConversion.objects.select_for_update().filter(application=locked).first()
    if existing and existing.status == ApplicationConversion.Status.COMPLETED:
        return existing
    if locked.status != ApplicationStatus.ENROLLMENT_READY:
        raise ApplicationConversionError("Application must be ready for enrollment.")
    try:
        placement = locked.placement
    except ApplicationPlacement.DoesNotExist as exc:
        raise ApplicationConversionError("Assign a grade and section before enrollment.") from exc

    if locked.application_type == ApplicationType.RETURNING_REGISTRATION:
        student = locked.returning_student
        if student is None:
            raise ApplicationConversionError("Returning student record is missing.")
    else:
        student = _create_student(locked, placement, actor)

    enrollment_request = SimpleNamespace(
        user=actor,
        data={"enrolled_as": placement.enrolled_as, "re_enroll": False},
    )
    enrollment = create_enrollment_for_student(
        student=student,
        academic_year=placement.academic_year,
        grade_level=placement.grade_level,
        section=placement.section,
        request=enrollment_request,
        status="active",
        notes=placement.notes,
    )
    if student.grade_level_id != placement.grade_level_id:
        student.grade_level = placement.grade_level
        student.updated_by = actor
        student.save(update_fields=["grade_level", "updated_by", "updated_at"])
    bill = AccountingStudentBill.objects.filter(enrollment=enrollment).first()
    conversion, _created = ApplicationConversion.objects.update_or_create(
        application=locked,
        defaults={
            "status": ApplicationConversion.Status.COMPLETED,
            "student": student,
            "enrollment": enrollment,
            "accounting_bill": bill,
            "error_code": "",
            "error_detail": "",
            "completed_at": timezone.now(),
            "created_by": actor,
            "updated_by": actor,
        },
    )
    transition_application(
        application=locked,
        to_status=ApplicationStatus.ENROLLED,
        actor=actor,
        reason="Enrollment and initial billing completed",
        metadata={
            "student_id": str(student.id),
            "enrollment_id": str(enrollment.id),
            "accounting_bill_id": str(bill.id) if bill else None,
        },
    )
    return conversion


def send_enrollment_confirmation(*, application, conversion, from_email):
    if not application.applicant_email:
        return
    bill = conversion.accounting_bill
    amount = bill.outstanding_amount if bill else None
    amount_text = f" Your current amount due is {amount}." if amount is not None else ""
    send_mail(
        subject=f"Enrollment completed: {application.request_id}",
        message=(
            f"Your registration has been approved and enrollment is complete."
            f"{amount_text} Sign in to your school account for billing details."
        ),
        from_email=from_email,
        recipient_list=[application.applicant_email],
        fail_silently=False,
    )

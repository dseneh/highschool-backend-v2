from datetime import date

from django.db import transaction

from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import StudentAccessPolicy

from common.status import AttendanceStatus
from common.status import EnrollmentStatus, StudentStatus
from common.utils import (
    create_model_data,
    get_object_by_uuid_or_fields,
    validate_required_fields,
)
from academics.models import MarkingPeriod, Section
from academics.models import AcademicYear, SchoolCalendarEvent, SchoolCalendarEventOccurrence, SchoolCalendarSettings

from ..models import Attendance, Enrollment, Student
from ..serializers import (
    AttendanceBulkUpsertSerializer,
    AttendanceSectionRosterSerializer,
    AttendanceSerializer,
)


def _count_school_days(academic_year):
    if not academic_year:
        return 0

    today = date.today()
    period_start = academic_year.start_date
    period_end = min(academic_year.end_date, today)

    if period_start > period_end:
        return 0

    settings = SchoolCalendarSettings.get_solo()
    operating_days = set(settings.operating_days or [1, 2, 3, 4, 5])

    blocked_days = set(
        SchoolCalendarEventOccurrence.objects.filter(
            occurrence_date__gte=period_start,
            occurrence_date__lte=period_end,
            event__event_type__in=[
                SchoolCalendarEvent.EventType.HOLIDAY,
                SchoolCalendarEvent.EventType.NON_SCHOOL_DAY,
            ],
        )
        .values_list("occurrence_date", flat=True)
        .distinct()
    )

    total = 0
    current = period_start
    while current <= period_end:
        if current.isoweekday() in operating_days and current not in blocked_days:
            total += 1
        current = current.fromordinal(current.toordinal() + 1)

    return total


def _build_student_attendance_summary(attendance_rows, school_days_elapsed):
    status_counts = {
        AttendanceStatus.ABSENT: 0,
        AttendanceStatus.LATE: 0,
        AttendanceStatus.EXCUSED: 0,
        AttendanceStatus.SICK: 0,
        AttendanceStatus.ON_LEAVE: 0,
        AttendanceStatus.HOLIDAY: 0,
        AttendanceStatus.PRESENT: 0,
    }

    recorded_absence_statuses = {
        AttendanceStatus.ABSENT,
        AttendanceStatus.LATE,
        AttendanceStatus.EXCUSED,
        AttendanceStatus.SICK,
        AttendanceStatus.ON_LEAVE,
        AttendanceStatus.HOLIDAY,
    }

    recorded_absences = 0
    for row in attendance_rows:
        status_key = row.status
        if status_key in status_counts:
            status_counts[status_key] += 1
        if status_key in recorded_absence_statuses:
            recorded_absences += 1

    implied_present_days = max(school_days_elapsed - recorded_absences, 0)
    attendance_rate = round((implied_present_days / school_days_elapsed) * 100, 2) if school_days_elapsed else 0

    return {
        "school_days_elapsed": school_days_elapsed,
        "recorded_absences": recorded_absences,
        "present_days": implied_present_days,
        "attendance_rate": attendance_rate,
        "status_counts": status_counts,
    }


def _build_attendance_summary(entries):
    total = len(entries)
    present = sum(1 for entry in entries if entry["status"] == AttendanceStatus.PRESENT)
    late = sum(1 for entry in entries if entry["status"] == AttendanceStatus.LATE)
    absent = sum(1 for entry in entries if entry["status"] == AttendanceStatus.ABSENT)
    excused = sum(1 for entry in entries if entry["status"] == AttendanceStatus.EXCUSED)
    sick = sum(1 for entry in entries if entry["status"] == AttendanceStatus.SICK)
    on_leave = sum(1 for entry in entries if entry["status"] == AttendanceStatus.ON_LEAVE)
    rate = round(((present + late) / total) * 100, 2) if total > 0 else 0

    return {
        "total": total,
        "present": present,
        "late": late,
        "absent": absent,
        "excused": excused,
        "sick": sick,
        "on_leave": on_leave,
        "attendance_rate": rate,
    }


def _parse_attendance_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return date.today()
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationError({"date": "Invalid date format. Use YYYY-MM-DD."}) from exc


def _build_section_roster_payload(section, marking_period, attendance_date, enrollments, attendance_map):
    entries = []
    for enrollment in enrollments:
        attendance = attendance_map.get(str(enrollment.id))
        entries.append(
            {
                "attendance_id": attendance.id if attendance else None,
                "enrollment_id": enrollment.id,
                "student_id": enrollment.student.id_number,
                "student_name": enrollment.student.get_full_name(),
                "section_name": enrollment.section.name,
                "status": attendance.status if attendance else AttendanceStatus.PRESENT,
                "notes": attendance.notes if attendance else None,
            }
        )

    return {
        "section": {
            "id": str(section.id),
            "name": section.name,
        },
        "marking_period": (
            {
                "id": str(marking_period.id),
                "name": marking_period.name,
                "start_date": marking_period.start_date,
                "end_date": marking_period.end_date,
            }
            if marking_period
            else None
        ),
        "date": attendance_date,
        "summary": _build_attendance_summary(entries),
        "entries": entries,
    }


class AttendanceSectionRosterView(APIView):
    permission_classes = [StudentAccessPolicy]

    def get_section(self, section_id):
        section = Section.objects.filter(id=section_id).first()
        if not section:
            raise NotFound("Section does not exist with this id")
        return section

    def get_marking_period_by_date(self, attendance_date, academic_year=None):
        queryset = MarkingPeriod.objects.filter(
            start_date__lte=attendance_date,
            end_date__gte=attendance_date,
        ).select_related("semester", "semester__academic_year")

        if academic_year:
            queryset = queryset.filter(semester__academic_year=academic_year)

        return queryset.order_by("start_date").first()

    def parse_date(self, value):
        if not value:
            raise ValidationError({"date": "Date query param is required (YYYY-MM-DD)."})
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError({"date": "Invalid date format. Use YYYY-MM-DD."}) from exc

    def get_enrollments(self, section):
        return list(
            Enrollment.objects.filter(section=section)
            .exclude(status__in=[EnrollmentStatus.CANCELED, EnrollmentStatus.WITHDRAWN])
            .select_related("student", "section", "academic_year", "grade_level")
            .order_by("student__first_name", "student__last_name")
        )

    def get(self, request, section_id):
        section = self.get_section(section_id)
        attendance_date = self.parse_date(request.query_params.get("date"))
        enrollments = self.get_enrollments(section)
        section_academic_year = enrollments[0].academic_year if enrollments else None
        marking_period = self.get_marking_period_by_date(attendance_date, section_academic_year)

        attendance_rows = Attendance.objects.filter(
            enrollment__in=enrollments,
            date=attendance_date,
        ).select_related("enrollment__student")
        attendance_map = {str(row.enrollment_id): row for row in attendance_rows}

        payload = _build_section_roster_payload(
            section,
            marking_period,
            attendance_date,
            enrollments,
            attendance_map,
        )
        serializer = AttendanceSectionRosterSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @transaction.atomic
    def post(self, request, section_id):
        section = self.get_section(section_id)
        serializer = AttendanceBulkUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = serializer.validated_data
        attendance_date = payload["date"]
        enrollments = self.get_enrollments(section)
        section_academic_year = enrollments[0].academic_year if enrollments else None
        marking_period = self.get_marking_period_by_date(attendance_date, section_academic_year)

        enrollment_map = {str(enrollment.id): enrollment for enrollment in enrollments}
        allowed_enrollment_ids = set(enrollment_map.keys())
        incoming_absences = {}

        for entry in payload["entries"]:
            enrollment_id = str(entry["enrollment_id"])
            enrollment = enrollment_map.get(enrollment_id)
            if not enrollment:
                raise ValidationError(
                    {"entries": f"Enrollment {entry['enrollment_id']} does not belong to this section."}
                )

            # Presence is implicit and should not be persisted.
            if entry["status"] == AttendanceStatus.PRESENT:
                continue

            student = enrollment.student
            if student.status in (
                StudentStatus.WITHDRAWN,
                StudentStatus.GRADUATED,
                StudentStatus.TRANSFERRED,
                StudentStatus.DELETED,
            ):
                continue

            incoming_absences[enrollment_id] = {
                "enrollment": enrollment,
                "status": entry["status"],
                "notes": entry.get("notes"),
            }

        existing_rows = Attendance.objects.filter(
            enrollment__in=enrollments,
            date=attendance_date,
        )
        existing_enrollment_ids = set(str(row.enrollment_id) for row in existing_rows)

        delete_enrollment_ids = existing_enrollment_ids.intersection(allowed_enrollment_ids).difference(
            set(incoming_absences.keys())
        )
        if delete_enrollment_ids:
            Attendance.objects.filter(
                enrollment_id__in=delete_enrollment_ids,
                date=attendance_date,
            ).delete()

        for enrollment_id, entry_data in incoming_absences.items():
            Attendance.objects.update_or_create(
                enrollment=entry_data["enrollment"],
                date=attendance_date,
                defaults={
                    "status": entry_data["status"],
                    "notes": entry_data["notes"],
                    "updated_by": request.user,
                    "created_by": request.user,
                },
            )

        refreshed_rows = Attendance.objects.filter(
            enrollment__in=enrollments,
            date=attendance_date,
        ).select_related("enrollment__student")
        attendance_map = {str(row.enrollment_id): row for row in refreshed_rows}
        response_payload = _build_section_roster_payload(
            section,
            marking_period,
            attendance_date,
            enrollments,
            attendance_map,
        )
        response_serializer = AttendanceSectionRosterSerializer(response_payload)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

class AttendanceListView(APIView):
    permission_classes = [StudentAccessPolicy]
    # permission_classes = [AllowAny]
    def get_student(self, student_id):
        try:
            student = get_object_by_uuid_or_fields(Student, student_id, fields=["id_number"])
            if student:
                return student
        except Student.DoesNotExist:
            pass

        # Backward compatibility: some clients still pass enrollment UUID here.
        enrollment = Enrollment.objects.select_related("student").filter(id=student_id).first()
        if enrollment:
            return enrollment.student

        raise NotFound(f"Student does not exist with lookup value '{student_id}'")

    def get_current_enrollment(self, student):
        return (
            Enrollment.objects.filter(student=student)
            .exclude(status__in=[EnrollmentStatus.CANCELED, EnrollmentStatus.WITHDRAWN])
            .select_related("student", "academic_year")
            .order_by("-academic_year__current", "-date_enrolled")
            .first()
        )

    def get_academic_year(self, student):
        enrollment = self.get_current_enrollment(student)
        if enrollment and enrollment.academic_year:
            return enrollment.academic_year
        return AcademicYear.get_current_academic_year()

    def get(self, request, student_id):
        student = self.get_student(student_id)
        academic_year = self.get_academic_year(student)

        attendance_filter = {"enrollment__student": student}
        if academic_year:
            attendance_filter["enrollment__academic_year"] = academic_year

        attendance = (
            Attendance.objects.filter(**attendance_filter)
            .select_related("enrollment__student", "enrollment__academic_year")
            .order_by("-date")
        )
        serializer = AttendanceSerializer(attendance, many=True)

        school_days_elapsed = _count_school_days(academic_year)
        summary = _build_student_attendance_summary(attendance, school_days_elapsed)

        payload = {
            "student": {
                "id": str(student.id),
                "id_number": student.id_number,
                "full_name": student.get_full_name(),
            },
            "academic_year": (
                {
                    "id": str(academic_year.id),
                    "name": academic_year.name,
                    "start_date": academic_year.start_date,
                    "end_date": academic_year.end_date,
                }
                if academic_year
                else None
            ),
            "summary": summary,
            "records": serializer.data,
        }

        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request, student_id):
        student = self.get_student(student_id)
        enrollment = self.get_current_enrollment(student)
        if not enrollment:
            return Response(
                {"detail": "No active enrollment found for this student."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Guard: reject attendance for withdrawn / inactive students
        if student.status in (StudentStatus.WITHDRAWN, StudentStatus.GRADUATED, StudentStatus.TRANSFERRED, StudentStatus.DELETED):
            return Response(
                {"detail": f"Cannot record attendance for a student with status '{student.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        req: dict = request.data

        required_fields = [
            "date",
            "status",
        ]

        validate_required_fields(request, required_fields)

        if req.get("status") not in AttendanceStatus.all():
            return Response({"detail": "Invalid attendance status"}, 400)

        attendance_date = _parse_attendance_date(req.get("date"))

        data = {
            "enrollment": enrollment,
            "status": req.get("status", AttendanceStatus.PRESENT),
            "date": attendance_date,
            "notes": req.get("notes"),
        }

        return create_model_data(request, data, Attendance, AttendanceSerializer)

class AttendanceDetailView(APIView):
    permission_classes = [StudentAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        try:
            return Attendance.objects.get(id=id)
        except Attendance.DoesNotExist:
            raise NotFound("Attendance does not exist with this id")

    def get(self, request, id):
        attendence = self.get_object(id)
        serializer = AttendanceSerializer(attendence)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        attendence = self.get_object(id)

        allowed_fields = [
            "date",
            "status",
        ]

        validate_required_fields(request, allowed_fields)

        if request.data.get("status") not in AttendanceStatus.all():
            return Response({"detail": "Invalid attendance status"}, 400)

        next_date = _parse_attendance_date(request.data.get("date"))
        next_status = request.data.get("status")

        attendence.date = next_date
        attendence.status = next_status
        attendence.updated_by = request.user
        attendence.save(update_fields=["date", "status", "updated_by", "updated_at"])

        serializer = AttendanceSerializer(attendence)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        attendence = self.get_object(id)
        attendence.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

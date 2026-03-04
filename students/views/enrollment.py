from datetime import datetime
import uuid

from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import StudentAccessPolicy

from common.status import EnrollmentStatus
from common.status import StudentStatus
from common.utils import (
    update_model_fields,
    validate_required_fields,
    get_object_by_uuid_or_fields,
)
from academics.models import AcademicYear, GradeLevel
from students.views.utils import create_enrollment_for_student

from ..models import Enrollment, Student
from ..serializers import EnrollmentSerializer

class EnrollmentListView(APIView):
    permission_classes = [StudentAccessPolicy]
    # permission_classes = [AllowAny]
    def get_object(self, id):
        try:
            return get_object_by_uuid_or_fields(
                Student, 
                id, 
                fields=['id_number', 'prev_id_number']
            )
        except Student.DoesNotExist:
            raise NotFound("Student does not exist with this id")

    def get(self, request, student_id):
        student = self.get_object(student_id)

        # 🔥 MEMORY FIX: Optimize enrollment loading
        enrollments = student.enrollments.select_related(
            "academic_year", "section__grade_level"
        )
        serializer = EnrollmentSerializer(
            enrollments, many=True, context={"request": request}
        )

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, student_id):
        student = self.get_object(student_id)

        # Guard: reject enrollment for inactive students (withdrawn students can re-enroll)
        if student.status in (StudentStatus.GRADUATED, StudentStatus.TRANSFERRED, StudentStatus.DELETED):
            return Response(
                {"detail": f"Cannot enroll a student with status '{student.status}'. Update the student's status first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        req: dict = request.data
        academic_year = req.get("academic_year")

        required_fields = [
            "academic_year",
            "grade_level",
        ]

        c_room = req.get("section")

        validate_required_fields(request, required_fields)
        if academic_year == "current":
            f = Q(current=True) | Q(status="active")
        else:
            f = Q(id=academic_year) | Q(name__iexact=academic_year)
        academic = AcademicYear.objects.filter(f).first()

        if not academic:
            return Response(
                {"detail": "Academic year does not exist with this id"}, 400
            )

        grade_level = GradeLevel.objects.filter(
            id=req.get("grade_level")
        ).first()

        if not grade_level:
            return Response({"detail": "Grade level does not exist with this id"}, 400)

        section = None
        if c_room:
            section = grade_level.sections.filter(id=c_room).first()

            if not section:
                return Response(
                    {
                        "detail": "Section does not exist with this id for the selected grade level"
                    },
                    400,
                )

        # section = Section.objects.filter(id=req.get("section")).first()

        # if not section:
        #     return Response({"detail": "Section room does not exist with this id"}, 400)

        # grade_level = section.grade_level

        # Check if the student is already enrolled in this academic year
        # if student.enrollments.filter(academic_year=academic).exists():
        #     return Response(
        #         {"detail": "Student is already enrolled in this academic year"},
        #         status=status.HTTP_400_BAD_REQUEST,
        #     )

        data = {
            "academic_year": academic,
            "grade_level": grade_level,
            "section": section,
            "status": req.get("status", "active"),
            "date_enrolled": req.get("date_enrolled", datetime.now().today()),
            "notes": req.get("notes"),
            "request": request,
            "student": student,
            "updated_by": request.user,
            "created_by": request.user,
        }

        # return create_model_data(
        #     request, data, student.enrollments, EnrollmentSerializer
        # )
        try:
            with transaction.atomic():
                # if no class room is provided, asign the student to the first class room of the grade level, if no class room is found, create a new class room
                # if not data["section"]:
                #     section = grade_level.sections.first()

                #     if not section:
                #         section = Section.objects.create(
                #             grade_level=grade_level,
                #             name=f"{grade_level.name}",
                #             updated_by=request.user,
                #             created_by=request.user,
                #         )
                # data["section"] = section
                # # create the enrollment
                # enrollment = student.enrollments.create(**data)

                # # create grade book
                # gls = grade_level.grade_level_subjects.all()

                # subjects = []
                # for gl in gls:
                #     subject = gl.subject
                #     subjects.append(subject)

                # if not gls:
                #     return Response(
                #         {"detail": "No subjects found for this class room"}, 400
                #     )
                # # for subject in subjects:
                # #     print('subject', subject.id, subject.name)

                # marking_periods = []
                # for semester in academic.semesters.all():
                #     marking_periods.extend(semester.marking_periods.all())
                #     print('marking periods', semester.id)

                # marking_periods = list(set(marking_periods))
                # if not marking_periods:
                #     return Response(
                #         {"detail": "No marking periods found for this academic year"},
                #         400,
                #     )

                # for subject in subjects:
                #     for marking_period in marking_periods:
                #         enrollment.grade_books.create(
                #             marking_period_id=marking_period.id,
                #             subject_id=subject.id,
                #             updated_by=request.user,
                #             created_by=request.user,
                #         )

                enrollment = create_enrollment_for_student(**data)

                # If student was withdrawn/transferred, reset status
                # (serializer will display as "enrolled" when current enrollment exists)
                if student.status in (StudentStatus.WITHDRAWN, StudentStatus.TRANSFERRED):
                    student.status = "enrolled"
                    student.save(update_fields=["status"])

                serializer = EnrollmentSerializer(
                    enrollment, context={"request": request}
                )
                return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class EnrollmentDetailView(APIView):
    permission_classes = [StudentAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        try:
            return Enrollment.objects.get(id=id)
        except Enrollment.DoesNotExist:
            raise NotFound("Enrollment does not exist with this id")

    def get(self, request, id):
        enrollment = self.get_object(id)
        serializer = EnrollmentSerializer(enrollment, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        enrollment = self.get_object(id)

        allowed_fields = [
            "section",
            "status",
            "date_enrolled",
            "notes",
            "active",
        ]

        if request.data.get("status") not in EnrollmentStatus.all():
            return Response({"detail": "Invalid enrollment status"}, 400)

        serializer = update_model_fields(
            request,
            enrollment,
            allowed_fields,
            EnrollmentSerializer,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        enrollment = self.get_object(id)
        enrollment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

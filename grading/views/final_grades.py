from decimal import Decimal
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import GradebookAccessPolicy

from academics.models import Section, Subject, AcademicYear, MarkingPeriod
from common.utils import get_object_by_uuid_or_fields
from grading.models import GradeBook, Assessment, Grade
from grading.serializers import (
    StudentFinalGradeOut,
    SimplifiedSectionFinalGradesOut,
    UnifiedStudentFinalGradesOut,
)
from grading.utils import (
    get_grading_config,
    calculate_marking_period_percentage,
)
from grading.services.pdf_report import generate_student_report_card_pdf
from students.models import Student, Enrollment

class StudentFinalGradeView(APIView):
    """
    GET /students/<student_id>/final-grades/gradebook/<gradebook_id>/?marking_period=<period_id>&status=<status>

    Returns a student's final grade with all grade items and individual grades

    Query Parameters:
        - marking_period: Optional marking period ID to filter grades
        - status: Optional grade status to filter by (defaults to 'any' for all grades)
                  Valid values: 'any', 'draft', 'pending', 'reviewed', 'submitted', 'approved'
    """

    def get(self, request, student_id, gradebook_id):
        # Get query parameters
        marking_period_id = request.query_params.get("marking_period")
        status = request.query_params.get("status", "any")

        # Validate status parameter
        valid_statuses = [choice[0] for choice in Grade.Status.choices] + ["any"]
        if status not in valid_statuses:
            return Response(
                {
                    "detail": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                },
                status=400,
            )

        # Get student
        student = get_object_by_uuid_or_fields(
                    Student, 
                    student_id, 
                    fields=['id_number']
                )

        # Get gradebook
        gradebook = get_object_or_404(GradeBook, pk=gradebook_id)

        # Get all marking periods for this gradebook's academic year
        marking_periods = (
            MarkingPeriod.objects.filter(
                semester__academic_year=gradebook.academic_year
            )
            .select_related("semester")
            .order_by("start_date")
        )

        # If marking_period_id is provided, filter to that specific marking period
        if marking_period_id:
            marking_periods = marking_periods.filter(id=marking_period_id)

        # Build marking periods data
        marking_periods_data = []

        for marking_period in marking_periods:
            # Get assessments for this marking period
            assessments = (
                Assessment.objects.filter(
                    gradebook=gradebook, marking_period=marking_period
                )
                .select_related("assessment_type", "marking_period")
                .order_by("due_date", "name")
            )

            # Calculate final percentage for this marking period
            final_percentage = calculate_marking_period_percentage(
                gradebook, student, marking_period, status=status
            )

            marking_periods_data.append(
                {
                    "marking_period": marking_period,
                    "assessments": assessments,
                    "final_percentage": final_percentage,
                }
            )

        # Create student object with only required fields
        student_obj = {
            "id": student.id,
            "id_number": student.id_number,
            "full_name": student.get_full_name(),
        }

        # Prepare response data
        data = {
            "gradebook": gradebook,
            "student": student_obj,
            "marking_periods": marking_periods_data,
        }

        serializer = StudentFinalGradeOut(
            data,
            context={"student_id": student.id, "request": request, "status": status},
        )
        return Response(serializer.data)

class StudentFinalGradesView(APIView):
    """
    Unified endpoint for student final grades with flexible filtering.

    GET /students/<student_id>/final-grades/academic-years/<academic_year_id>/

    Query Parameters:
        - gradebook=<gradebook_id>: Optional. Filter by specific gradebook
        - marking_period=<period_id>: Optional. Filter by specific marking period
        - include_average=<true|false>: Optional. Include averages (default: false)
        - include_assessment=<true|false>: Optional. Include assessments (default: true)
        - status=<status>: Optional. Filter by grade status (default: 'any')
                          Valid values: 'any', 'draft', 'pending', 'reviewed', 'submitted', 'approved'

    Response Structure:
        {
            "id": "student-uuid",
            "id_number": "0121774",
            "full_name": "Michael Ashley Blair",
            "section": {"id": "...", "name": "General"},
            "grade_level": {"id": "...", "name": "Nursery 1"},
            "academic_year": {"id": "...", "name": "2025-2026"},
            "config": {
                "grading_style": "single_entry",
                // ... grading configuration
            },
            "gradebooks": [  // Array of gradebooks, or single object if gradebook filter is used
                {
                    "id": "gradebook-uuid",
                    "name": "Art - General",
                    "calculation_method": "weighted",
                    "subject": {"id": "...", "name": "Art"},
                    "averages": {  // Only if include_average=true
                        "semester_averages": [{"id": "...", "name": "Semester 2", "average": 97}],
                        "final_average": 97
                    },
                    "marking_periods": [  // Array, or "marking_period" object if marking_period filter is used
                        {
                            "id": "mp-uuid",
                            "name": "Marking Period 1",
                            "final_percentage": 0,
                            "letter_grade": "-",
                            "status": null,
                            "semester": {"id": "...", "name": "Semester 1"},
                            "assessments": [...]  // Only if include_assessment=true
                        }
                    ]
                }
            ],
            "overall_averages": {  // Only if include_average=true
                "semester_averages": [{"id": "...", "name": "Semester 2", "average": 97}],
                "final_average": 97
            },
            "total_gradebooks": 14
        }

    Filtering Behavior:
        - If gradebook is specified, "gradebooks" becomes a single object (not array)
        - If marking_period is specified, "marking_periods" becomes "marking_period" object (not array)
        - Both filters can be combined
    """

    def get(self, request, student_id, academic_year_id):
        # Extract query parameters
        gradebook_id = request.query_params.get("gradebook")
        marking_period_id = request.query_params.get("marking_period")
        status = request.query_params.get("status", "any")
        include_average = (
            request.query_params.get("include_average", "false").lower() == "true"
        )
        include_assessment = (
            request.query_params.get("include_assessment", "true").lower() == "true"
        )

        # Validate status parameter
        valid_statuses = [choice[0] for choice in Grade.Status.choices] + ["any"]
        if status not in valid_statuses:
            return Response(
                {
                    "detail": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                },
                status=400,
            )

        # Get student (support both ID and ID number)
        student = get_object_by_uuid_or_fields(
                            Student, 
                            student_id, 
                            fields=['id_number']
                        )
        # Get academic year
        academic_year = get_object_or_404(AcademicYear, pk=academic_year_id)

        # Get marking period if specified
        marking_period = None
        if marking_period_id:
            marking_period = get_object_or_404(MarkingPeriod, pk=marking_period_id)

        # Get student's enrollment for this academic year
        try:
            enrollment = Enrollment.objects.get(
                student=student, academic_year=academic_year
            )
        except Enrollment.DoesNotExist:
            return Response(
                {"detail": "Student is not enrolled in this academic year."}, status=404
            )

        # Get gradebooks
        gradebooks_query = (
            GradeBook.objects.filter(
                section=enrollment.section, academic_year=academic_year
            )
            .select_related(
                "subject",
                "section",
                "academic_year",
                "section_subject__subject",
            )
            .order_by("section_subject__subject__name")
        )

        # Filter by gradebook if specified
        if gradebook_id:
            gradebooks_query = gradebooks_query.filter(id=gradebook_id)

        if not gradebooks_query.exists():
            if gradebook_id:
                return Response(
                    {
                        "detail": f"Gradebook not found for student {student.id_number} for academic year {enrollment.academic_year.name}"
                    },
                    status=404,
                )
            return Response(
                {
                    "detail": f"No gradebooks found for student {student.get_full_name()} for academic year {enrollment.academic_year.name}"
                },
                status=404,
            )

        # Build gradebooks data
        gradebooks_data = []
        for gradebook in gradebooks_query:
            gradebooks_data.append(
                {
                    "gradebook": gradebook,
                }
            )

        # Prepare response data
        data = {
            "student": student,
            "section": enrollment.section,
            "grade_level": enrollment.section.grade_level,
            "academic_year": academic_year,
            "gradebooks_data": gradebooks_data,
            "filter_marking_period": marking_period,
            "single_gradebook": bool(
                gradebook_id
            ),  # Flag to indicate single gradebook mode
        }

        # Create context
        context = {
            "request": request,
            "status": status,
            "include_average": include_average,
            "include_assessment": include_assessment,
        }

        serializer = UnifiedStudentFinalGradesOut(data, context=context)
        return Response(serializer.data)

class SectionFinalGradesView(APIView):
    """
    GET /sections/<section_id>/final-grades/?academic_year=<year_id>&data_by=subject&subject=<subject_id>&marking_period=<period_id>&status=<status>&include_average=<bool>&include_assessment=<bool>&student=<id_or_id_number>
    GET /sections/<section_id>/final-grades/?academic_year=<year_id>&data_by=all_subjects&marking_period=<period_id>&status=<status>&include_average=<bool>&include_assessment=<bool>&student=<id_or_id_number>

    Returns final grades for students in a section with marking_periods array structure.

    Query Parameters:
        - academic_year: Required. Academic year ID
        - data_by: 'subject' or 'all_subjects' (default: 'all_subjects')
        - subject: Required when data_by=subject. Subject ID to filter
        - marking_period: Optional. If provided, filters results to this marking period only (works with both data_by modes)
        - status: Grade status filter (default: 'any')
                  Valid values: 'any', 'draft', 'pending', 'reviewed', 'submitted', 'approved'
        - include_average: 'true' or 'false' (default: 'false'). Include averages object in response
        - include_assessment: 'true' or 'false' (default: 'true'). Include assessments array in response
        - student: Optional. Filter by specific student (can be student ID or ID number)

    Response Structure (data_by=subject):
        {
            "section": {"id": "...", "name": "..."},
            "grade_level": {"id": "...", "name": "..."},
            "subject": {"id": "...", "name": "..."},
            "academic_year": {"id": "...", "name": "..."},
            "gradebook": {"id": "...", "name": "...", "calculation_method": "..."},
            "config": {...},
            "students": [
                {
                    "id": "...",
                    "id_number": "...",
                    "full_name": "...",
                    "averages": {  // Only if include_average=true
                        "semester_averages": [
                            {"id": "...", "name": "Semester 1", "average": 90}
                        ],
                        "final_average": 90
                    },
                    "marking_periods": [
                        {
                            "id": "...",
                            "name": "Marking Period 1",
                            "final_percentage": 90,
                            "letter_grade": "A",
                            "status": null,
                            "semester": {"id": "...", "name": "Semester 1"},
                            "assessments": [...]  // Only if include_assessment=true
                        }
                    ]
                }
            ],
            "class_average": 0,
            "total_students": 7
        }

    Response Structure (data_by=all_subjects):
        {
            "section": {"id": "...", "name": "..."},
            "academic_year": {"id": "...", "name": "..."},
            "status": "any",
            "data_by": "all_subjects",
            "config": {
                "grading_style": "single_entry",
                "grading_style_display": "Single Entry (Final Grades Only)",
                // ... other grading settings (shared by all subjects)
            },
            "subjects": [
                // Array of objects with same structure as data_by=subject response
                // NOTE: config is NOT included in individual subjects to reduce payload
            ],
            "total_subjects": 5
        }
    """

    def get(self, request, section_id):
        academic_year_id = request.query_params.get("academic_year")
        data_by = request.query_params.get("data_by", "all_subjects")
        subject_id = request.query_params.get("subject")
        marking_period_id = request.query_params.get("marking_period")
        status = request.query_params.get("status", "any")
        include_average = (
            request.query_params.get("include_average", "false").lower() == "true"
        )
        include_assessment = (
            request.query_params.get("include_assessment", "true").lower() == "true"
        )
        student_filter = request.query_params.get("student")  # Can be ID or ID number

        if not academic_year_id:
            return Response(
                {"detail": "academic_year parameter is required."}, status=400
            )

        # Validate status parameter
        valid_statuses = [choice[0] for choice in Grade.Status.choices] + ["any"]
        if status not in valid_statuses:
            return Response(
                {
                    "detail": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                },
                status=400,
            )

        # Validate data_by parameter
        if data_by not in ["all_subjects", "subject"]:
            return Response(
                {
                    "detail": "Invalid data_by parameter. Must be 'all_subjects' or 'subject'."
                },
                status=400,
            )

        # If data_by is subject, subject parameter is required
        if data_by == "subject" and not subject_id:
            return Response(
                {"detail": "subject parameter is required when data_by=subject."},
                status=400,
            )

        # Get required objects
        section = get_object_or_404(Section, pk=section_id)
        academic_year = get_object_or_404(AcademicYear, pk=academic_year_id)

        # Get marking period if specified
        marking_period = None
        if marking_period_id:
            marking_period = get_object_or_404(MarkingPeriod, pk=marking_period_id)

        # Add context parameters
        context = {
            "request": request,
            "status": status,
            "include_average": include_average,
            "include_assessment": include_assessment,
        }

        if data_by == "subject":
            return self._handle_single_subject(
                request,
                section,
                academic_year,
                subject_id,
                marking_period,
                status,
                student_filter,
                context,
            )
        else:
            return self._handle_all_subjects(
                request,
                section,
                academic_year,
                marking_period,
                status,
                student_filter,
                context,
            )

    def _handle_single_subject(
        self,
        request,
        section,
        academic_year,
        subject_id,
        marking_period,
        status="any",
        student_filter=None,
        context=None,
    ):
        """Handle single subject view"""
        subject = get_object_or_404(Subject, pk=subject_id)

        # Get the gradebook for this section/subject/year
        try:
            gradebook = GradeBook.objects.get(
                section=section,
                subject=subject,
                academic_year=academic_year,
            )
        except GradeBook.DoesNotExist:
            return Response(
                {"detail": "No gradebook found for this section/subject/year."},
                status=404,
            )

        # Get all enrolled students in this section for this academic year
        enrollments = (
            Enrollment.objects.filter(section=section, academic_year=academic_year)
            .select_related("student")
            .order_by("student__last_name", "student__first_name")
        )

        # Filter by student if specified (supports both ID and ID number)
        if student_filter:
            enrollments = enrollments.filter(
                Q(student__id=student_filter) | Q(student__id_number=student_filter)
            )

        if not enrollments.exists():
            if student_filter:
                return Response(
                    {"detail": "Student not found in this section."}, status=404
                )
            return Response(
                {"detail": "No students enrolled in this section."}, status=404
            )

        # Build students_data - simplified since serializer will handle all the details
        students_data = []
        for enrollment in enrollments:
            student_data = {
                "student": enrollment.student,
            }
            students_data.append(student_data)

        # Get semester information if marking_period is available
        # semester = marking_period.semester if marking_period else None

        # Prepare response data for single subject
        response_data = {
            "section": section,
            "subject": subject,
            "academic_year": academic_year,
            "marking_period": marking_period,  # Pass marking_period to serializer
            "status": status,
            "data_by": "subject",
            "gradebook": gradebook,
            "students": students_data,
            "class_average": Decimal("0"),  # Will be calculated if needed
            "total_students": len(students_data),
        }
        # Use the simplified serializer for single subject
        serializer = SimplifiedSectionFinalGradesOut(
            response_data, context=context or {"request": request, "status": status}
        )
        return Response(serializer.data)

    def _handle_all_subjects(
        self,
        request,
        section,
        academic_year,
        marking_period=None,
        status="any",
        student_filter=None,
        context=None,
    ):
        """Handle all subjects view"""
        # Get all gradebooks for this section and academic year
        gradebooks = (
            GradeBook.objects.filter(section=section, academic_year=academic_year)
            .select_related("subject")
            .order_by("subject__name")
        )

        if not gradebooks.exists():
            return Response(
                {"detail": "No gradebooks found for this section/year."}, status=404
            )

        # Get all enrolled students once
        enrollments = (
            Enrollment.objects.filter(section=section, academic_year=academic_year)
            .select_related("student")
            .order_by("student__last_name", "student__first_name")
        )

        # Filter by student if specified (supports both ID and ID number)
        if student_filter:
            enrollments = enrollments.filter(
                Q(student__id=student_filter) | Q(student__id_number=student_filter)
            )

        if not enrollments.exists():
            if student_filter:
                return Response(
                    {"detail": "Student not found in this section."}, status=404
                )
            return Response(
                {"detail": "No students enrolled in this section."}, status=404
            )

        # Extract config from the first gradebook (all gradebooks in the section share the same config)
        config = None
        first_gradebook = gradebooks.first()
        if first_gradebook:
            config = get_grading_config(first_gradebook)
        subjects_data = []

        # Update context to skip config in individual subjects
        updated_context = (context or {"request": request, "status": status}).copy()
        updated_context["skip_config"] = True

        for gradebook in gradebooks:
            # Build students_data - simplified since serializer will handle all the details
            students_data = []
            for enrollment in enrollments:
                student_data = {
                    "student": enrollment.student,
                }
                students_data.append(student_data)

            subject_data = {
                "section": section,
                "subject": gradebook.subject,
                "academic_year": academic_year,
                "marking_period": marking_period,  # Pass marking_period to serializer
                "status": status,
                "gradebook": gradebook,
                "students": students_data,
                "class_average": 0,  # Will be calculated if needed
                "total_students": len(students_data),
            }

            # Serialize each subject's data with updated context
            serializer = SimplifiedSectionFinalGradesOut(
                subject_data, context=updated_context
            )
            subjects_data.append(serializer.data)

        response_data = {
            "section": {"id": section.id, "name": section.name},
            "academic_year": {"id": academic_year.id, "name": academic_year.name},
            "status": status,
            "data_by": "all_subjects",
            "subjects": subjects_data,
            "total_subjects": len(subjects_data),
        }

        # Add config at the top level if it exists
        if config:
            response_data["config"] = config

        return Response(response_data)

class StudentReportCardPDFView(APIView):
    """
    Generate and download student report card as PDF.

    GET /grading/students/<student_id>/report-card/?academic_year=<year_id>

    Query Parameters:
        - academic_year: Academic year ID (defaults to current if not provided)

    Returns:
        PDF file download
    """

    def get(self, request, student_id, academic_year_id):
        # Get student (support both ID and ID number)
        try:
            f = Q(id=student_id) | Q(id_number=student_id)
            student = Student.objects.get(f)
        except Student.DoesNotExist:
            return Response({"detail": "Student does not exist."}, status=404)

        # Get academic year (default to current)
        # academic_year_id = request.query_params.get("academic_year")
        if academic_year_id:
            try:
                academic_year = AcademicYear.objects.get(id=academic_year_id)
            except AcademicYear.DoesNotExist:
                return Response({"detail": "Academic year does not exist."}, status=404)
        else:
            # Get current academic year
            academic_year = AcademicYear.objects.filter(current=True).first()
            if not academic_year:
                return Response(
                    {"detail": "No current academic year."},
                    status=404,
                )

        # Get enrollment
        try:
            enrollment = Enrollment.objects.get(
                student=student, academic_year=academic_year
            )
        except Enrollment.DoesNotExist:
            return Response(
                {"detail": "Student is not enrolled in this academic year."}, status=404
            )

        # Generate and return PDF
        return generate_student_report_card_pdf(student, academic_year, enrollment)

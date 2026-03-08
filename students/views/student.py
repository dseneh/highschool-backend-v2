
import logging

from django.db import transaction, router, connection
from django.db.models import Q, Sum, Avg, Count
from django.db.models.deletion import Collector
from django.db.models.signals import pre_delete
from django.db.utils import OperationalError, ProgrammingError
from rest_framework import parsers, permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import StudentAccessPolicy

from common.filter import get_student_queryparams
from common.images import update_model_image
from common.utils import (
    StudentBulkProcessor,
    StudentImportValidator,
    format_import_response,
    read_csv_safely,
    update_model_fields,
    validate_sample_data,
    get_object_by_uuid_or_fields,
)
from academics.models import AcademicYear, GradeLevel
from students.models import Student, Enrollment, StudentEnrollmentBill, Attendance
from students.serializers import StudentDetailSerializer, StudentSerializer
from students.views.utils import create_enrollment_for_student

# Import business logic (framework-agnostic)
from business.students.services import student_service
from business.students.adapters import (
    create_student_in_db,
    get_next_student_sequence,
    check_student_exists,
    django_student_to_data,
    student_has_enrollments,
    student_has_bills,
)

logger = logging.getLogger(__name__)


def _table_exists(table_name: str) -> bool:
    try:
        return table_name in connection.introspection.table_names()
    except Exception:
        return False


class StudentPageNumberPagination(PageNumberPagination):
    page_size = 10  # Set your desired page size here
    page_size_query_param = "page_size"


class StudentListView(APIView):
    permission_classes = [StudentAccessPolicy]
    def get(self, request):
        students = Student.objects.select_related(
            "grade_level"
        ).prefetch_related("enrollments__academic_year")

        # # Apply query string filters
        filter_fields = [
            "first_name",
            "last_name",
            "middle_name",
            "gender",
            # "status",
            "grade_level",
        ]

        # filter_kwargs = {}
        # for field in filter_fields:
        #     value = request.query_params.get(field)
        #     if value is not None:
        #         filter_kwargs[field] = value
        # if filter_kwargs:
        #     students = students.filter(**filter_kwargs)
        # is_enrolled = request.query_params.get("is_enrolled", "")
        status = request.query_params.get("status", "")

        query_params = request.query_params.copy()

        # Parse enrollment status using business logic
        enrollment_statuses, other_statuses = student_service.parse_enrollment_status_filter(status)
        
        # Update query_params with cleaned status
        if other_statuses:
            query_params["status"] = ",".join(other_statuses)
        else:
            query_params.pop("status", None)

        query = get_student_queryparams(query_params, filter_fields)
        if query:
            students = students.filter(query)
            
        # Apply enrollment filtering
        if enrollment_statuses:
            students1 = students2 = None
            if "enrolled" in enrollment_statuses:
                students1 = students.filter(
                    enrollments__academic_year__current=True
                ).distinct()
            if "not_enrolled" in enrollment_statuses:
                students2 = students.exclude(
                    enrollments__academic_year__current=True
                ).distinct()
            
            if students1 is not None and students2 is not None:
                students = students1 | students2
            elif students1 is not None:
                students = students1
            elif students2 is not None:
                students = students2

        registered_grade_level = query_params.get("registered_grade_level")

        if registered_grade_level:
            gl = GradeLevel.objects.filter(
                id=registered_grade_level
            ).first()
            if not gl:
                return Response({"detail": "Grade level does not exist."}, status=400)
            students = students.filter(grade_level=gl)

        # Sorting using business logic
        ordering = request.query_params.get("ordering", "id_number")
        sort_fields, is_descending = student_service.get_sorting_fields(ordering)
        
        if is_descending:
            sort_fields = [f"-{f}" for f in sort_fields]
            students = students.order_by(*sort_fields)
        else:
            students = students.order_by(ordering)

        # Pagination
        paginator = StudentPageNumberPagination()
        paginated_qs = paginator.paginate_queryset(students, request)
        serializer = StudentSerializer(
            paginated_qs, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        req_data: dict = request.data
        
        # Use business logic for validation (framework-agnostic)
        is_valid, errors = student_service.validate_student_creation(req_data)
        if not is_valid:
            return Response(
                {"detail": errors[0] if errors else "Validation failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Use business logic for duplicate check
        if check_student_exists(
            req_data.get("first_name"),
            req_data.get("last_name"),
            req_data.get("date_of_birth"),
            req_data.get("prev_id_number")
        ):
            return Response(
                {
                    "detail": "Student already exists with either the same name and date of birth or previous id number."
                },
                status=400,
            )

        # Get grade level (Django-specific query)
        gl = req_data.get("grade_level")
        grade_level = GradeLevel.objects.filter(id=gl).first()
        if not grade_level:
            return Response(
                {"detail": "Current grade level does not exist."},
                status=400,
            )

        # Business logic: Check enrollment rules
        cr = req_data.get("section")
        enroll_student = student_service.should_auto_enroll(req_data)
        current_academic_year = AcademicYear.objects.filter(current=True).first()
        if enroll_student:
            if not current_academic_year:
                return Response(
                    {"detail": "No current academic year found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Business logic: Prepare student data
        # Get tenant from connection schema (django-tenants automatic isolation)
        from django.db import connection
        from core.models import Tenant
        
        tenant = Tenant.objects.filter(schema_name=connection.schema_name).first()
        if not tenant:
            return Response(
                {"detail": "Tenant context could not be resolved."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        school_code = int(str(tenant.id_number)[-2:]) if tenant.id_number else 1
        student_seq = get_next_student_sequence()
        
        data = student_service.prepare_student_data_for_creation(
            req_data, school_code, student_seq
        )
        
        # Add Django-specific fields
        data["grade_level"] = grade_level

        # Database operation using adapter
        try:
            with transaction.atomic():
                student = create_student_in_db(
                    data,
                    created_by=request.user,
                    updated_by=request.user
                )

                # if user pass enroll_student as true, then create the student enrollment
                if enroll_student:
                    classes = grade_level.sections
                    if cr:
                        section = classes.filter(id=cr).first() or classes.first()
                    else:
                        section = grade_level.sections.create(
                            name=f"General",
                            updated_by=request.user,
                            created_by=request.user,
                        )
                    # i would like to create the enrollment for the student with all the other models required.
                    # we can send an api request to the enrollment endpoint to create the enrollment
                    create_enrollment_for_student(
                        student=student,
                        academic_year=current_academic_year,
                        grade_level=grade_level,
                        section=section,
                        request=request,
                        status="active",
                    )

                serializer = StudentSerializer(student, context={"request": request})
                
                return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {"detail": f"An error occurred: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class StudentSummaryView(APIView):
    """
    Dashboard summary statistics for students.
    GET /students/summary/
    
    Returns:
    {
        "total_students": int,
        "total_staff": int,
        "total_teachers": int,
        "academic_year": str,
        "total_enrolled": int,
        "pending_bills": float,
        "total_courses": int,
        "active_sections": int,
        "avg_attendance": float
    }
    """
    permission_classes = [StudentAccessPolicy]

    def get(self, request):
        from academics.models import Section

        default_summary = {
            "total_students": 0,
            "total_staff": 0,
            "total_teachers": 0,
            "academic_year": "N/A",
            "total_enrolled": 0,
            "pending_bills": 0.0,
            "total_courses": 0,
            "active_sections": 0,
            "avg_attendance": 0,
        }

        # Tenants can exist before student-related tables are provisioned.
        # Return an empty summary instead of throwing SQL errors.
        if not _table_exists("student"):
            logger.warning("Student table missing for tenant; returning empty student summary")
            return Response(default_summary, status=status.HTTP_200_OK)

        try:
            # Get current academic year
            current_academic_year = AcademicYear.objects.filter(current=True).first()
            academic_year_name = current_academic_year.name if current_academic_year else "N/A"

            # Count total students
            total_students = Student.objects.all().count()

            # Count total staff and teachers
            try:
                from staff.models import Staff

                staff_qs = Staff.objects.all()
                total_staff = staff_qs.count()
                total_teachers = staff_qs.filter(
                    Q(is_teacher=True) | Q(position__teaching_role=True)
                ).distinct().count()
            except:
                total_staff = 0
                total_teachers = 0

            # Count total enrolled students in current academic year
            if current_academic_year:
                total_enrolled = Enrollment.objects.filter(
                    academic_year=current_academic_year
                ).values('student').distinct().count()
            else:
                total_enrolled = 0

            # Calculate pending bills (active bills from StudentEnrollmentBill)
            # Note: StudentEnrollmentBill doesn't have a 'status' field, only 'active'
            pending_bills = StudentEnrollmentBill.objects.filter(
                active=True
            ).aggregate(total=Sum('amount'))['total'] or 0

            # Count active courses/sections
            # Note: Sections don't have academic_year field directly,
            # they're linked to academic years through enrollments
            if current_academic_year:
                # Get sections that have enrollments in the current academic year
                active_sections = Section.objects.filter(
                    enrollments__academic_year=current_academic_year,
                    active=True
                ).distinct().count()
                
                # Count unique subjects across those sections
                from academics.models import SectionSubject
                total_courses = SectionSubject.objects.filter(
                    section__enrollments__academic_year=current_academic_year,
                    section__active=True,
                    active=True
                ).values('subject').distinct().count()
            else:
                total_courses = 0
                active_sections = 0

            if current_academic_year:
                attendance_totals = Attendance.objects.filter(
                    enrollment__academic_year=current_academic_year
                ).aggregate(
                    total_records=Count("id"),
                    present_records=Count(
                        "id",
                        filter=Q(status__in=["present", "late", "excused"]),
                    ),
                )

                total_records = attendance_totals.get("total_records") or 0
                present_records = attendance_totals.get("present_records") or 0
                avg_attendance = (
                    (present_records / total_records) * 100 if total_records > 0 else 0
                )
            else:
                avg_attendance = 0

            return Response({
                "total_students": total_students,
                "total_staff": total_staff,
                "total_teachers": total_teachers,
                "academic_year": academic_year_name,
                "total_enrolled": total_enrolled,
                "pending_bills": float(pending_bills),
                "total_courses": total_courses,
                "active_sections": active_sections,
                "avg_attendance": round(float(avg_attendance), 2) if avg_attendance else 0,
            })

        except (ProgrammingError, OperationalError) as e:
            logger.warning(f"Student summary unavailable due to missing tables: {e}")
            return Response(default_summary, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"detail": f"Error retrieving student summary: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class StudentDetailView(APIView):
    permission_classes = [StudentAccessPolicy]
    def get_object(self, id):
        try:
            return get_object_by_uuid_or_fields(
                Student, 
                id, 
                fields=['id_number', 'prev_id_number']
            )
        except Student.DoesNotExist:
            raise NotFound("Student does not exist with this id")

    def get(self, request, id):
        student = self.get_object(id)
        serializer = StudentDetailSerializer(student, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        student = self.get_object(id)
        
        # Convert to business data for validation
        student_data = django_student_to_data(student)
        
        # Business logic: Validate update
        is_valid, errors = student_service.validate_student_update(
            student_data, 
            request.data
        )
        if not is_valid:
            return Response(
                {"detail": errors[0] if errors else "Validation failed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        allowed_fields = [
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "gender",
            "prev_id_number",
            "place_of_birth",
            "email",
            "phone_number",
            "address",
            "city",
            "state",
            "postal_code",
            "country",
            "status",
            "entry_date",
            "grade_level",
            "date_of_graduation",
        ]

        serializer = update_model_fields(
            request, student, allowed_fields, StudentSerializer
        )
        
        # Handle photo update if provided
        photo = request.FILES.get("photo")
        if photo:
            from common.images import update_model_image
            update_model_image(student, "photo", photo)
        
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        student = self.get_object(id)
        force_delete = request.query_params.get("force_delete", "false").lower()
        
        # Business logic: Check if student can be deleted
        if force_delete not in ["1", "true", "yes"]:
            student_data = django_student_to_data(student)
            can_delete, reason = student_service.can_delete_student(
                student_data,
                has_enrollments=student_has_enrollments(student),
                has_bills=student_has_bills(student)
            )
            
            if not can_delete:
                return Response(
                    {"detail": reason},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # If force delete or business rules allow deletion
        if force_delete in ["1", "true", "yes"]:
            # Force delete: handle deletion carefully to avoid foreign key constraints
            try:
                with transaction.atomic():
                    # No need to disconnect signals for user_account (now just a string reference)
                    
                    # Manually delete related objects in the correct order to avoid FK constraint issues
                    from students.models import (
                        Enrollment,
                        StudentPaymentSummary,
                        Attendance,
                        StudentEnrollmentBill,
                    )
                    from finance.models import Transaction
                    from grading.models import Grade

                    # Get fresh student instance
                    student_fresh = student.__class__.objects.get(id=student.id)

                    # Get all enrollments for this student
                    enrollments = list(student_fresh.enrollments.all())

                    # Delete in order: objects that reference enrollments first, then enrollments, then student
                    for enrollment in enrollments:
                        # Delete payment summaries (reference enrollments)
                        StudentPaymentSummary.objects.filter(
                            enrollment=enrollment
                        ).delete()

                        # Delete attendance records (reference enrollments)
                        Attendance.objects.filter(enrollment=enrollment).delete()

                        # Delete student bills (reference enrollments)
                        StudentEnrollmentBill.objects.filter(
                            enrollment=enrollment
                        ).delete()

                    # Delete grades (they reference both student and enrollment)
                    # Grades will cascade delete from enrollment FK
                    Grade.objects.filter(student=student_fresh).delete()

                    # Delete transactions (they reference student directly)
                    Transaction.objects.filter(student=student_fresh).delete()

                    # Delete enrollments (all related objects should be gone now)
                    for enrollment in enrollments:
                        enrollment.delete()

                    # Now delete the student (should have no remaining FK references)
                    student_fresh.delete()

                    # Note: User accounts are in public schema and managed separately
                    # Consider cleanup job to remove orphaned user accounts if needed

                return Response(status=status.HTTP_204_NO_CONTENT)
            except Exception as e:
                import logging
                import traceback

                logger = logging.getLogger(__name__)
                error_details = str(e)
                error_traceback = traceback.format_exc()
                student_id_number = getattr(student, "id_number", "unknown")
                logger.error(
                    f"Error deleting student {student_id_number}: {error_details}\n{error_traceback}",
                    exc_info=True,
                )

                # Try to provide more helpful error message
                if "FOREIGN KEY constraint failed" in error_details:
                    # Re-fetch the student from DB to check relationships (transaction rolled back)
                    try:
                        student_id = getattr(student, "id", None)
                        if student_id:
                            student_fresh = self.get_object(id)
                            blocking_info = []
                            try:
                                enrollments_count = student_fresh.enrollments.count()
                                if enrollments_count > 0:
                                    blocking_info.append(
                                        f"{enrollments_count} enrollment(s)"
                                    )
                            except Exception:
                                pass

                            try:
                                if hasattr(student_fresh, "transactions"):
                                    transactions_count = (
                                        student_fresh.transactions.count()
                                    )
                                    if transactions_count > 0:
                                        blocking_info.append(
                                            f"{transactions_count} transaction(s)"
                                        )
                            except Exception:
                                pass

                            try:
                                if hasattr(student_fresh, "grades_by_student"):
                                    grades_count = (
                                        student_fresh.grades_by_student.count()
                                    )
                                    if grades_count > 0:
                                        blocking_info.append(f"{grades_count} grade(s)")
                            except Exception:
                                pass

                            if blocking_info:
                                error_details = f"FOREIGN KEY constraint failed. Student has related records: {', '.join(blocking_info)}. The deletion may have failed due to database constraints."
                    except Exception:
                        # If we can't re-fetch, just use the original error
                        pass

                return Response(
                    {"detail": f"Error deleting student: {error_details}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Soft delete: check if the student has any enrollments
        if student.enrollments.exists():
            student.active = False
            student.status = "deleted"
            student.save()
            return Response(
                {
                    "detail": "Cannot delete student with existing enrollments. Student has been deactivated instead."
                },
                status=status.HTTP_201_CREATED,
            )

        # No enrollments, safe to delete
        try:
            with transaction.atomic():
                # User accounts are in public schema - no FK relationship to handle
                # Just delete the student directly
                
                # Use Django's collector for proper cascading deletes
                using = router.db_for_write(student.__class__, instance=student)
                collector = Collector(using=using)
                collector.collect([student])
                collector.delete()

            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                f"Error deleting student {student.id_number}: {str(e)}", exc_info=True
            )
            return Response(
                {"detail": f"Error deleting student: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class StudentWithdrawView(APIView):
    permission_classes = [StudentAccessPolicy]
    """POST /students/<id>/withdraw — withdraw a student."""

    def get_object(self, id):
        try:
            return get_object_by_uuid_or_fields(
                Student,
                id,
                fields=["id_number", "prev_id_number"],
            )
        except Student.DoesNotExist:
            raise NotFound("Student does not exist with this id")

    def post(self, request, id):
        student = self.get_object(id)

        # Validate payload
        withdrawal_date = request.data.get("withdrawal_date")
        withdrawal_reason = request.data.get("withdrawal_reason")

        if not withdrawal_date:
            return Response(
                {"detail": "withdrawal_date is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update student status & withdrawal fields
        student.status = "withdrawn"
        student.withdrawal_date = withdrawal_date
        student.withdrawal_reason = withdrawal_reason or None
        student.save(update_fields=["status", "withdrawal_date", "withdrawal_reason"])

        # Cancel current-year enrollment if it exists
        current_enrollment = student.enrollments.filter(
            academic_year__current=True
        ).first()
        if current_enrollment:
            current_enrollment.status = "withdrawn"
            current_enrollment.save(update_fields=["status"])

        serializer = StudentDetailSerializer(student, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class StudentReinstateView(APIView):
    permission_classes = [StudentAccessPolicy]
    """POST /students/<id>/reinstate — reinstate a withdrawn/transferred student."""

    def get_object(self, id):
        try:
            return get_object_by_uuid_or_fields(
                Student,
                id,
                fields=["id_number", "prev_id_number"],
            )
        except Student.DoesNotExist:
            raise NotFound("Student does not exist with this id")

    def post(self, request, id):
        student = self.get_object(id)

        if student.status not in ("withdrawn", "transferred"):
            return Response(
                {"detail": f"Cannot reinstate a student with status '{student.status}'. Only withdrawn or transferred students can be reinstated."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reinstate student — set status to enrolled, clear withdrawal fields
        student.status = "enrolled"
        student.withdrawal_date = None
        student.withdrawal_reason = None
        student.save(update_fields=["status", "withdrawal_date", "withdrawal_reason"])

        # Reinstate current-year enrollment if it was withdrawn
        current_enrollment = student.enrollments.filter(
            academic_year__current=True
        ).first()
        if current_enrollment and current_enrollment.status == "withdrawn":
            current_enrollment.status = "completed"
            current_enrollment.save(update_fields=["status"])

        serializer = StudentDetailSerializer(student, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class StudentImportView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser]

    def post(self, request, grade_level_id):
        try:
            grade_level = GradeLevel.objects.get(id=grade_level_id)
        except GradeLevel.DoesNotExist:
            return Response(
                {"detail": "Grade level not found."}, status=status.HTTP_404_NOT_FOUND
            )

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Validate file name matches grade level convention
        file_name = file_obj.name.lower()
        file_prefix = (
            file_name.split("_")[0] if "_" in file_name else file_name.split(".")[0]
        )
        expected_prefix = (
            grade_level.short_name.lower()
            if hasattr(grade_level, "short_name") and grade_level.short_name
            else f"g{grade_level.level}".lower()
        )

        if file_prefix != expected_prefix:
            return Response(
                {
                    "error": f"File name validation failed. If you intend to upload this file for {grade_level.name}, expected file name should start with '{expected_prefix}_', instead of got '{file_prefix}_'. Please rename your file to follow the convention: {expected_prefix}_students.csv"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # File safety validation using utility
        safety_errors = StudentImportValidator.validate_file_safety(file_obj)
        if safety_errors:
            return Response(
                {"errors": safety_errors}, status=status.HTTP_400_BAD_REQUEST
            )

        # Read and validate CSV using utility
        try:
            df = read_csv_safely(file_obj)
        except Exception as e:
            return Response(
                {"error": f"Failed to read CSV file: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate CSV structure using utility
        structure_errors = StudentImportValidator.validate_csv_structure(df)
        if structure_errors:
            return Response(
                {"errors": structure_errors}, status=status.HTTP_400_BAD_REQUEST
            )

        # Pre-validate sample data using utility
        validation_errors = validate_sample_data(df, sample_size=100)

        # If there are validation errors in the sample, return them
        if validation_errors:
            return Response(
                {
                    "error": "Validation failed",
                    "validation_errors": validation_errors[:20],
                    "total_errors_found": len(validation_errors),
                    "note": f"Showing first 20 errors from sample of {min(100, len(df))} rows",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Process in chunks with individual transactions per chunk
        total_created = 0
        all_errors = []

        # Process DataFrame in chunks
        for i in range(0, len(df), StudentImportValidator.CHUNK_SIZE):
            chunk = df.iloc[i : i + StudentImportValidator.CHUNK_SIZE]

            # Validate chunk data
            chunk_validation_errors = []
            for index, row in chunk.iterrows():
                row_errors = StudentImportValidator.validate_row_data(row, index + 2)
                chunk_validation_errors.extend(row_errors)

            if chunk_validation_errors:
                all_errors.extend(chunk_validation_errors)
                continue

            # Process valid chunk using utility
            (
                students_to_create,
                users_to_create,
                chunk_errors,
            ) = StudentBulkProcessor.process_chunk(chunk, grade_level, request.user)

            # Add any processing errors to the error list
            if chunk_errors:
                all_errors.extend(chunk_errors)

            # Create students one by one with individual transactions
            if students_to_create:
                created_students = []
                for student_obj in students_to_create:
                    try:
                        # Use individual transaction for each student
                        with transaction.atomic():
                            student_obj.save()
                            created_students.append(student_obj)

                    except Exception as create_error:
                        # Log the error and continue with next student
                        chunk_errors.append(
                            {
                                "row": f"Student {student_obj.first_name} {student_obj.last_name}",
                                "error": f"Failed to create: {str(create_error)}",
                            }
                        )

                total_created += len(created_students)

                # Create user accounts using utility
                if created_students:
                    try:
                        StudentBulkProcessor.create_user_accounts(
                            created_students, request.user
                        )
                    except Exception as user_error:
                        # Log user creation errors but don't fail the whole import
                        all_errors.append(
                            {
                                "row": "User account creation",
                                "error": f"Failed to create user accounts: {str(user_error)}",
                            }
                        )

            # Add any creation errors to the error list
            if chunk_errors:
                all_errors.extend(chunk_errors)

        # Format response using utility
        response_data = format_import_response(total_created, all_errors, success=True)
        return Response(
            response_data,
            status=(
                status.HTTP_201_CREATED
                if total_created > 0
                else status.HTTP_400_BAD_REQUEST
            ),
        )

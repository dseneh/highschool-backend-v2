from rest_framework import serializers
from academics.models import AcademicYear

from common.utils import get_enrollment_bill_summary
from common.serializers import PhotoURLMixin

from ..models import Student
from .enrollment import EnrollmentListSerializer


class StudentSerializer(PhotoURLMixin, serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            "id",
            "prev_id_number",
            "id_number",
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "gender",
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
            "place_of_birth",
            "photo",
            "entry_as",
            "withdrawal_date",
            "withdrawal_reason",
        ]

    def to_representation(self, instance: Student):
        response = super().to_representation(instance)
        response["full_name"] = instance.get_full_name()
        context = self.context
        request = context.get("request")
        show_rank = context.get("show_rank", False)
        show_grade_average = context.get("show_grade_average", False)
        show_balance = context.get("show_balance", False)
        show_paid = context.get("show_paid", False)
        ranking_lookup = context.get("ranking_lookup", {}) or {}

        # Return grade_level as a nested object in API responses
        # while keeping write payloads backward compatible (UUID accepted).
        if instance.grade_level:
            response["grade_level"] = {
                "id": instance.grade_level.id,
                "name": instance.grade_level.name,
                "level": instance.grade_level.level,
            }
        else:
            response["grade_level"] = None
        
        # Photo URL is automatically handled by PhotoURLMixin
        
        selected_academic_year = context.get("academic_year")
        if selected_academic_year is None:
            selected_academic_year_id = context.get("academic_year_id")
            if selected_academic_year_id:
                selected_academic_year = AcademicYear.objects.filter(
                    id=selected_academic_year_id
                ).first()

        # Resolve the enrollment for the selected academic year when provided.
        if selected_academic_year:
            current_enrollment = instance.enrollments.filter(
                academic_year=selected_academic_year
            ).first()
        else:
            current_enrollment = instance.enrollments.filter(
                academic_year__current=True
            ).first()

        # Determine current grade level based on priority
        current_grade_level = None
        if current_enrollment:
            # Priority 1: Use grade level from current enrollment
            current_grade_level = current_enrollment.grade_level
        else:
            # Priority 2: Get previous enrollment and use next_grade_level
            previous_enrollment = instance.enrollments.order_by(
                "-academic_year__start_date"
            ).first()
            if (
                previous_enrollment
                and hasattr(previous_enrollment, "next_grade_level")
                and previous_enrollment.next_grade_level
            ):
                current_grade_level = previous_enrollment.next_grade_level
            else:
                # Priority 3: Use student's grade_level field
                current_grade_level = instance.grade_level

        # Add current grade level to response
        if current_grade_level:
            response["current_grade_level"] = {
                "id": current_grade_level.id,
                "name": current_grade_level.name,
                "level": current_grade_level.level,
            }
        else:
            response["current_grade_level"] = None

        is_active = response["status"] not in [
            "inactive",
            "graduated",
            "suspended",
            "deleted",
            "withdrawn",
        ]
        if current_enrollment:

            include_billing = context.get("include_billing", True)
            include_payment_plan = context.get("include_payment_plan", True)
            include_payment_status = context.get("include_payment_status", True)

            request = self.context.get("request")

            response["current_enrollment"] = EnrollmentListSerializer(
                current_enrollment,
                context={
                    "request": request if request else None,
                    "include_billing": include_billing,
                    "include_payment_plan": include_payment_plan,
                    "include_payment_status": include_payment_status,
                },
            ).data
            # response["status"] = "enrolled"
            if is_active:
                response["status"] = "enrolled"
        else:
            if is_active:
                response["status"] = "not enrolled"

        response["is_enrolled"] = instance.is_enrolled()
        enrollment_count = (
            instance.enrollments.count()
        )  # 🔥 MEMORY FIX: Use count() instead of len(.all())
        # response["enrollment_bill_summary"] = instance.get_balance_summary()
        response["number_of_enrollments"] = enrollment_count
        response["can_delete"] = enrollment_count == 0

        # Optionally include grade average if requested (legacy heavy mode)
        include_grades = context.get("include_grades", False)
        if include_grades and not show_grade_average and current_enrollment:
            from grading.utils import calculate_student_overall_average
            try:
                average_data = calculate_student_overall_average(
                    student=instance,
                    academic_year=current_enrollment.academic_year,
                    status="approved",
                )
                response["grade_average"] = average_data["final_average"]
            except Exception:
                # If grade calculation fails, set to None
                response["grade_average"] = None

        # Lightweight ranking/average response controlled by query params.
        if show_rank or show_grade_average:
            metric = ranking_lookup.get(str(instance.id))
            if show_grade_average:
                response["grade_average"] = metric.get("score") if metric else None
            if show_rank:
                response["rank"] = metric.get("rank") if metric else None

        if show_balance:
            balance_value = getattr(instance, "balance_total", None)
            try:
                response["balance"] = float(balance_value) if balance_value is not None else None
            except (TypeError, ValueError):
                response["balance"] = None

        if show_paid:
            paid_value = getattr(instance, "paid_total", None)
            try:
                response["paid"] = float(paid_value) if paid_value is not None else None
            except (TypeError, ValueError):
                response["paid"] = None

        return response


class StudentPaymentStatusSerializer(serializers.ModelSerializer):
    """Minimal serializer for payment status views - only essential fields"""

    class Meta:
        model = Student
        fields = [
            "id",
            "id_number",
            "first_name",
            "last_name",
            "photo",
        ]

    def to_representation(self, instance: Student):
        response = super().to_representation(instance)
        response["full_name"] = instance.get_full_name()

        context = self.context
        request = self.context.get("request")

        # Ensure photo URL is absolute if available
        if request and response.get("photo"):
            response["photo"] = request.build_absolute_uri(response["photo"])

        # Get current enrollment - use prefetched data if available to avoid N+1 queries
        # The view prefetches enrollments for the specific academic_year, so use the first one
        current_enrollment = None
        if (
            hasattr(instance, "_prefetched_objects_cache")
            and "enrollments" in instance._prefetched_objects_cache
        ):
            # Use prefetched enrollments (already filtered by academic_year in the view)
            prefetched_enrollments = instance._prefetched_objects_cache["enrollments"]
            if prefetched_enrollments:
                current_enrollment = prefetched_enrollments[0]
        else:
            # Fallback: query if not prefetched (shouldn't happen in payment status view)
            current_enrollment = (
                instance.enrollments.filter(academic_year__current=True)
                .select_related("grade_level", "section", "academic_year")
                .first()
            )

        # Add grade level and section from current enrollment
        if current_enrollment:
            if current_enrollment.grade_level:
                response["grade_level"] = {
                    "id": current_enrollment.grade_level.id,
                    "name": current_enrollment.grade_level.name,
                }
            else:
                response["grade_level"] = None

            if current_enrollment.section:
                response["section"] = {
                    "id": current_enrollment.section.id,
                    "name": current_enrollment.section.name,
                }
            else:
                response["section"] = None

            # Include current_enrollment object with payment plan/status
            include_billing = context.get("include_billing", True)
            include_payment_plan = context.get("include_payment_plan", True)
            include_payment_status = context.get("include_payment_status", True)

            response["current_enrollment"] = EnrollmentListSerializer(
                current_enrollment,
                context={
                    "request": request if request else None,
                    "include_billing": include_billing,
                    "include_payment_plan": include_payment_plan,
                    "include_payment_status": include_payment_status,
                },
            ).data
        else:
            response["grade_level"] = None
            response["section"] = None
            response["current_enrollment"] = None

        return response


class StudentDetailSerializer(StudentSerializer):
    class Meta(StudentSerializer.Meta):
        fields = StudentSerializer.Meta.fields

    def to_representation(self, instance):
        response = super().to_representation(instance)
        # 🔥 MEMORY FIX: Optimize enrollment loading with select_related/prefetch_related
        optimized_enrollments = instance.enrollments.select_related(
            "academic_year", "section__grade_level"
        ).prefetch_related("section")
        request = self.context.get("request")
        response["enrollments"] = EnrollmentListSerializer(
            optimized_enrollments,
            many=True,
            context={"request": request} if request else {},
        ).data

        # Safely get user account by id_number lookup (cross-schema)
        user_account = None
        if instance.user_account_id_number or instance.id_number:
            from users.models import User
            from django.db.models import Q
            # try:
            f = Q(id_number=instance.user_account_id_number) | Q(id_number=instance.id_number)
            user_account = User.objects.filter(f).first()
            # except Exception:
            #     pass
        
        # Roles removed - permission system has been removed
        roles = []

        response["user_account"] = (
            {
                "id": user_account.id,
                "id_number": user_account.id_number,
                "username": user_account.username,
                "first_name": instance.first_name,
                "last_name": instance.last_name,
                "email": user_account.email,
                "is_active": user_account.is_active,
                "is_staff": user_account.is_staff,
                "role": user_account.role,
                "status": user_account.status,
                "last_login": user_account.last_login,
                "last_password_updated": user_account.last_password_updated,
            }
            if user_account
            else None
        )

        # TODO: Grade book logic needs to be rewritten to use grading.GradeBook
        # The old students.GradeBook has been removed in favor of the grading app's assessment-based gradebook
        # This section should be updated to:
        # 1. Query grading.GradeBook for the student's enrollments
        # 2. Aggregate grades from grading.Grade model (assessment grades)
        # 3. Use grading.utils.calculate_student_overall_average() for overall calculations
        
        # Group grade books by semester
        # grade_books = GradeBook.objects.filter(enrollment__student=instance)
        semesters = {}
        unique_subjects = set()  # Track unique subjects

        # Commenting out old GradeBook logic - needs rewrite using grading app
        """
        for gb in grade_books:
            # Add subject to unique subjects set
            unique_subjects.add(gb.subject.id)

            semester = gb.marking_period.semester
            semester_id = semester.id
            if semester_id not in semesters:
                semesters[semester_id] = {
                    "id": semester.id,
                    "name": semester.name,
                    "start_date": semester.start_date,
                    "end_date": semester.end_date,
                    "marking_periods": [],
                    "semester_sum": 0,
                    "semester_count": 0,
                }
            grade_avg = (
                (gb.grade / gb.grade_target) * 100
                if gb.grade_target and gb.grade is not None and gb.grade_target > 0
                else 0
            )
            semesters[semester_id]["marking_periods"].append(
                {
                    "id": gb.marking_period.id,
                    "name": gb.marking_period.name,
                    "grade": gb.grade,
                    "grade_target": gb.grade_target,
                    "grade_average": grade_avg,
                }
            )
            semesters[semester_id]["semester_sum"] += grade_avg
            semesters[semester_id]["semester_count"] += 1
        """  # End of commented out GradeBook logic

        # Calculate total average using standardized grading calculation
        # Import the utility function from grading
        from grading.utils import calculate_student_overall_average

        # Get the current academic year
        current_enrollment = instance.enrollments.filter(
            academic_year__current=True
        ).first()

        if current_enrollment:
            # Use the standardized calculation
            average_data = calculate_student_overall_average(
                student=instance,
                academic_year=current_enrollment.academic_year,
                status="approved",  # Can be 'approved' for official grades only
            )
            total_average = average_data["final_average"]
        else:
            # Fallback to 0 if no current enrollment
            total_average = 0

        # response["semesters"] = semester_list
        response["total_average"] = total_average
        response["total_subjects"] = len(unique_subjects)
        return response

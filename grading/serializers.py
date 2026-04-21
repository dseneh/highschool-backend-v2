from rest_framework import serializers
from .models import (
    AssessmentType,
    GradeBook,
    Assessment,
    Grade,
    GradeLetter,
    HonorCategory,
    DefaultAssessmentTemplate,
)
from .utils import get_grading_config, get_letter_grade
from students.models import Student


def format_numeric_value(value):
    """
    Format numeric values to show whole numbers when decimals are 0,
    otherwise show one decimal place.
    """
    if value is None:
        return None

    try:
        float_value = float(value)
        # Round to 1 decimal place
        rounded_value = round(float_value, 1)

        # If the decimal part is 0, return as int
        if rounded_value == int(rounded_value):
            return int(rounded_value)
        else:
            return rounded_value
    except (ValueError, TypeError):
        return value


class AssessmentTypeOut(serializers.ModelSerializer):
    class Meta:
        model = AssessmentType
        fields = [
            "id",
            "active",
            "name",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class GradeBookOut(serializers.ModelSerializer):

    class Meta:
        model = GradeBook
        fields = [
            "id",
            "active",
            "name",
            "calculation_method",
            "section_subject",
            "academic_year",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def __init__(self, *args, **kwargs):
        self.include_stats = kwargs.pop("include_stats", False)
        super().__init__(*args, **kwargs)

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["grade_level"] = {
            "id": instance.section_subject.section.grade_level.id,
            "name": instance.section_subject.section.grade_level.name,
        }
        response["section"] = {
            "id": instance.section_subject.section.id,
            "name": instance.section_subject.section.name,
        }
        response["subject"] = {
            "id": instance.section_subject.subject.id,
            "name": instance.section_subject.subject.name,
        }
        response["academic_year"] = {
            "id": instance.academic_year.id,
            "name": instance.academic_year.name,
        }

        # Resolve teacher assignment for this section-subject.
        # If multiple assignments exist, return the most recently updated one.
        teacher_assignment = (
            instance.section_subject.staff_teachers.select_related("teacher")
            .order_by("-updated_at", "-created_at")
            .first()
        )
        teacher = teacher_assignment.teacher if teacher_assignment else None
        response["teacher"] = (
            {
                "id": str(teacher.id),
                "full_name": teacher.get_full_name() if hasattr(teacher, "get_full_name") else "",
                "id_number": teacher.id_number,
            }
            if teacher
            else None
        )

        # Include statistics if requested
        if self.include_stats:
            stats = instance.get_gradebook_statistics()
            response["statistics"] = {
                "total_assessments": stats["total_assessments"],
                "calculated_assessments": stats["calculated_assessments"],
                "overall_average": format_numeric_value(stats["overall_average"]),
                "students_with_grades": stats["students_with_grades"],
                "total_enrolled_students": stats["total_enrolled_students"],
            }
            
            # Include workflow status summary
            workflow_status = instance.get_workflow_status_summary()
            response["workflow_status"] = workflow_status

        return response


class AssessmentOut(serializers.ModelSerializer):
    gradebook = serializers.SerializerMethodField()
    assessment_type = serializers.SerializerMethodField()
    marking_period = serializers.SerializerMethodField()
    grade_level = serializers.SerializerMethodField()
    section = serializers.SerializerMethodField()

    class Meta:
        model = Assessment
        fields = [
            "id",
            "active",
            "gradebook",
            "assessment_type",
            "marking_period",
            "grade_level",
            "section",
            "name",
            "max_score",
            "weight",
            "due_date",
            "is_calculated",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_gradebook(self, obj):
        return {
            "id": obj.gradebook.id,
            "name": obj.gradebook.name,
        }

    def get_assessment_type(self, obj):
        return {
            "id": obj.assessment_type.id,
            "name": obj.assessment_type.name,
        }

    def get_marking_period(self, obj):
        return {
            "id": obj.marking_period.id,
            "name": obj.marking_period.name,
            "short_name": obj.marking_period.short_name,
            "start_date": (
                obj.marking_period.start_date.isoformat()
                if obj.marking_period.start_date
                else None
            ),
            "end_date": (
                obj.marking_period.end_date.isoformat()
                if obj.marking_period.end_date
                else None
            ),
        }

    def get_grade_level(self, obj):
        return {
            "id": obj.gradebook.section.grade_level.id,
            "name": obj.gradebook.section.grade_level.name,
        }

    def get_section(self, obj):
        return {
            "id": obj.gradebook.section.id,
            "name": obj.gradebook.section.name,
        }

    def to_representation(self, instance):
        response = super().to_representation(instance)

        # Include statistics if requested
        request = self.context.get("request")
        if request and request.query_params.get("include_stats") == "true":
            response["statistics"] = self._get_assessment_statistics(instance)

        return response

    def _get_assessment_statistics(self, instance):
        """Calculate and return grade item statistics"""
        from django.db.models import Count, Avg, Max, Min, Q
        from decimal import Decimal

        # Get all grades for this assessment
        all_grades = instance.grades.all()

        # Get only grades with scores (graded students)
        graded = all_grades.filter(score__isnull=False)

        # Base statistics
        stats = {
            "total_students": all_grades.count(),
            "graded_students": graded.count(),
            "ungraded_students": all_grades.filter(score__isnull=True).count(),
            "pending_approval": all_grades.filter(status="pending").count(),
        }

        # Score-based statistics (only for graded assignments)
        if graded.exists():
            score_stats = graded.aggregate(
                highest_score=Max("score"),
                lowest_score=Min("score"),
                average_score=Avg("score"),
            )

            # Calculate percentage statistics
            max_score = float(instance.max_score) if instance.max_score else 100

            stats.update(
                {
                    "highest_score": score_stats["highest_score"],
                    "lowest_score": score_stats["lowest_score"],
                    "average_score": round(
                        (
                            float(score_stats["average_score"])
                            if score_stats["average_score"]
                            else 0
                        ),
                        2,
                    ),
                    "highest_percentage": round(
                        (
                            (float(score_stats["highest_score"]) / max_score * 100)
                            if score_stats["highest_score"] is not None
                            else 0
                        ),
                        2,
                    ),
                    "lowest_percentage": round(
                        (
                            (float(score_stats["lowest_score"]) / max_score * 100)
                            if score_stats["lowest_score"] is not None
                            else 0
                        ),
                        2,
                    ),
                    "average_percentage": round(
                        (
                            (float(score_stats["average_score"]) / max_score * 100)
                            if score_stats["average_score"]
                            else 0
                        ),
                        2,
                    ),
                }
            )

            # Grade distribution (pass/fail based on common grading scales)
            passing_threshold = max_score * 0.6  # 60% passing threshold
            passing_grades = graded.filter(score__gte=passing_threshold).count()
            failing_grades = graded.filter(score__lt=passing_threshold).count()

            stats.update(
                {
                    "passing_grades": passing_grades,
                    "failing_grades": failing_grades,
                    "pass_rate": round(
                        (
                            (passing_grades / graded.count() * 100)
                            if graded.count() > 0
                            else 0
                        ),
                        2,
                    ),
                }
            )

        else:
            # No graded assignments yet
            stats.update(
                {
                    "highest_score": None,
                    "lowest_score": None,
                    "average_score": 0,
                    "highest_percentage": 0,
                    "lowest_percentage": 0,
                    "average_percentage": 0,
                    "passing_grades": 0,
                    "failing_grades": 0,
                    "pass_rate": 0,
                }
            )

        return stats


class GradeOut(serializers.ModelSerializer):
    assessment = serializers.SerializerMethodField()
    student = serializers.SerializerMethodField()
    section = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()

    class Meta:
        model = Grade
        fields = [
            "id",
            "active",
            "assessment",
            "student",
            "section",
            "subject",
            "score",
            "status",
            "comment",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_assessment(self, obj):
        return {
            "id": obj.assessment.id,
            "name": obj.assessment.name,
        }

    def get_student(self, obj):
        return {
            "id": obj.student.id,
            "id_number": obj.student.id_number,
            "full_name": obj.student.get_full_name(),
        }

    def get_section(self, obj):
        return {"id": obj.section.id, "name": obj.section.name}

    def get_subject(self, obj):
        return {"id": obj.subject.id, "name": obj.subject.name}


class AssessmentsWithGradeOut(serializers.ModelSerializer):
    """Grade item serializer that includes student's grade and percentage"""

    student_grade = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    percentage = serializers.SerializerMethodField()
    gradebook = serializers.SerializerMethodField()
    assessment_type = serializers.SerializerMethodField()
    marking_period = serializers.SerializerMethodField()
    semester = serializers.SerializerMethodField()

    class Meta:
        model = Assessment
        fields = [
            "id",
            "active",
            "gradebook",
            "name",
            "assessment_type",
            "marking_period",
            "semester",
            "max_score",
            "weight",
            "due_date",
            "is_calculated",
            "score",
            "status",
            "student_grade",
            "percentage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_gradebook(self, obj):
        return {
            "id": obj.gradebook.id,
            "name": obj.gradebook.name,
        }

    def get_assessment_type(self, obj):
        return {
            "id": obj.assessment_type.id,
            "name": obj.assessment_type.name,
        }

    def get_marking_period(self, obj):
        return {
            "id": obj.marking_period.id,
            "name": obj.marking_period.name,
            "short_name": obj.marking_period.short_name,
            "start_date": (
                obj.marking_period.start_date.isoformat()
                if obj.marking_period.start_date
                else None
            ),
            "end_date": (
                obj.marking_period.end_date.isoformat()
                if obj.marking_period.end_date
                else None
            ),
        }

    def get_semester(self, obj):
        return {
            "id": obj.marking_period.semester.id,
            "name": obj.marking_period.semester.name,
        }

    def get_score(self, obj):
        """Get the student's score for this assessment"""
        student_id = self.context.get("student_id")
        if not student_id:
            return None

        try:
            grade = Grade.objects.get(assessment=obj, student_id=student_id)
            return (
                format_numeric_value(grade.score) if grade.score is not None else None
            )
        except Grade.DoesNotExist:
            return None

    def get_status(self, obj):
        """Get the student's grade status for this assessment"""
        student_id = self.context.get("student_id")
        if not student_id:
            return None

        try:
            grade = Grade.objects.get(assessment=obj, student_id=student_id)
            return grade.status
        except Grade.DoesNotExist:
            return None

    def get_student_grade(self, obj):
        """Get the student's grade for this grade item"""
        student_id = self.context.get("student_id")
        if not student_id:
            return None

        try:
            grade = Grade.objects.get(assessment=obj, student_id=student_id)
            return GradeOut(grade, context=self.context).data
        except Grade.DoesNotExist:
            return None

    def get_percentage(self, obj):
        """Calculate percentage for this grade item"""
        student_id = self.context.get("student_id")
        if not student_id:
            return None

        try:
            grade = Grade.objects.get(assessment=obj, student_id=student_id)
            if grade.score is not None and obj.max_score:
                percentage = float(grade.score) / float(obj.max_score) * 100
                return format_numeric_value(percentage)
        except Grade.DoesNotExist:
            pass
        return None


class StudentFinalGradeOut(serializers.Serializer):
    """Serializer for student's final grade in a gradebook grouped by marking periods"""

    gradebook = GradeBookOut(read_only=True)
    student = serializers.SerializerMethodField()
    config = serializers.SerializerMethodField()
    marking_periods = serializers.SerializerMethodField()

    def get_student(self, obj):
        """Get student info"""
        student = obj.get("student")
        if student:
            # If it's already a dictionary (from view), return it directly
            if isinstance(student, dict):
                return student
            # If it's a Student instance, serialize it
            from students.serializers import StudentSerializer

            return StudentSerializer(student).data
        return None

    def get_config(self, obj):
        """Get grading configuration from settings"""
        gradebook = obj.get("gradebook")
        return get_grading_config(gradebook)

    def get_marking_periods(self, obj):
        """Get marking periods with their assessments and calculated percentages"""
        marking_periods_data = obj.get("marking_periods", [])
        gradebook = obj.get("gradebook")
        student = obj.get("student")
        student_id = (
            student.get("id")
            if isinstance(student, dict)
            else student.id if student else None
        )
        result = []

        for mp_data in marking_periods_data:
            marking_period = mp_data.get("marking_period")
            assessments = mp_data.get("assessments", [])
            final_percentage = mp_data.get("final_percentage")

            # Format assessments with student grades
            formatted_assessments = []
            marking_period_status = None  # Track status from first assessment

            for assessment in assessments:
                # Get student's grade for this assessment
                score = None
                status = None
                percentage = None

                if student_id:
                    try:
                        grade = Grade.objects.get(
                            assessment=assessment, student_id=student_id
                        )
                        score = (
                            format_numeric_value(grade.score)
                            if grade.score is not None
                            else None
                        )
                        status = grade.status

                        # Set marking period status from first assessment with a grade
                        if marking_period_status is None and status:
                            marking_period_status = status

                        # Calculate percentage if score exists
                        if grade.score is not None and assessment.max_score:
                            percentage = format_numeric_value(
                                float(grade.score) / float(assessment.max_score) * 100
                            )
                    except Grade.DoesNotExist:
                        pass

                formatted_assessments.append(
                    {
                        "id": assessment.id,
                        "name": assessment.name,
                        "max_score": format_numeric_value(assessment.max_score),
                        "weight": format_numeric_value(assessment.weight),
                        "due_date": assessment.due_date,
                        "is_calculated": assessment.is_calculated,
                        "score": score,
                        "status": status,
                        "percentage": percentage,
                    }
                )

            # Calculate letter grade
            letter_grade = "-"
            formatted_percentage = (
                format_numeric_value(final_percentage)
                if final_percentage is not None
                else None
            )

            if final_percentage is not None and gradebook:
                try:
                    letter_grade = get_letter_grade(float(final_percentage))
                except (AttributeError, ValueError):
                    pass

            result.append(
                {
                    "id": marking_period.id,
                    "name": marking_period.name,
                    "short_name": marking_period.short_name,
                    "start_date": (
                        marking_period.start_date.isoformat()
                        if marking_period.start_date
                        else None
                    ),
                    "end_date": (
                        marking_period.end_date.isoformat()
                        if marking_period.end_date
                        else None
                    ),
                    "semester": {
                        "id": marking_period.semester.id,
                        "name": marking_period.semester.name,
                    },
                    "assessments": formatted_assessments,
                    "final_percentage": formatted_percentage,
                    "letter_grade": letter_grade,
                    "status": marking_period_status,
                }
            )

        return result


class StudentAllFinalGradesOut(serializers.Serializer):
    """Improved serializer for student's all final grades - cleaner structure"""

    student = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()
    semester = serializers.SerializerMethodField()
    section = serializers.SerializerMethodField()
    grade_level = serializers.SerializerMethodField()
    config = serializers.SerializerMethodField()
    gradebooks = serializers.SerializerMethodField()
    total_subjects = serializers.IntegerField(read_only=True)
    total_average = serializers.SerializerMethodField()
    overall_letter_grade = serializers.SerializerMethodField()

    def get_student(self, obj):
        """Get basic student info"""
        student = obj.get("student")
        if not student:
            return None
        return {
            "id": student.id,
            "id_number": student.id_number,
            "full_name": student.get_full_name(),
        }

    def get_academic_year(self, obj):
        """Get academic year info"""
        academic_year = obj.get("academic_year")
        if not academic_year:
            return None
        return {"id": academic_year.id, "name": academic_year.name}

    def get_semester(self, obj):
        """Get semester info if available"""
        semester = obj.get("semester")
        if not semester:
            return None
        return {"id": semester.id, "name": semester.name}

    def get_section(self, obj):
        """Get section info from first enrollment/gradebook"""
        gradebooks = obj.get("gradebooks", [])
        if gradebooks:
            first_gradebook = gradebooks[0]
            section = first_gradebook.get("gradebook").section_subject.section
            return {"id": section.id, "name": section.name}
        return None

    def get_grade_level(self, obj):
        """Get grade level info from student's current enrollment"""
        gradebooks = obj.get("gradebooks", [])
        if gradebooks:
            first_gradebook = gradebooks[0]
            grade_level = first_gradebook.get(
                "gradebook"
            ).section_subject.section.grade_level
            return {"id": grade_level.id, "name": grade_level.name}
        return None

    def get_config(self, obj):
        """Get grading configuration from settings"""
        gradebooks = obj.get("gradebooks", [])
        if gradebooks:
            first_gradebook = gradebooks[0].get("gradebook")
            return get_grading_config(first_gradebook)
        return None

    def get_gradebooks(self, obj):
        """Get simplified gradebooks structure"""
        gradebooks = obj.get("gradebooks", [])
        student = obj.get("student")
        result = []

        for gb_data in gradebooks:
            gradebook = gb_data.get("gradebook")
            assessments = gb_data.get("assessments", [])
            final_percentage = gb_data.get("final_percentage")

            # Calculate letter grade and format percentage
            letter_grade = "-"
            formatted_percentage = None

            if gradebook and final_percentage is not None:
                # Ensure we have a valid percentage
                if hasattr(final_percentage, "__float__") or isinstance(
                    final_percentage, (int, float)
                ):
                    try:
                        percentage_value = float(final_percentage)
                        formatted_percentage = format_numeric_value(percentage_value)
                        letter_grade = get_letter_grade(percentage_value)
                    except (ValueError, TypeError, AttributeError) as e:
                        print(
                            f"Debug - Error converting percentage: {e}"
                        )
                        pass

            # Format grade items with student scores
            formatted_items = []
            for item in assessments:
                # Get student's grade for this item
                score = None
                student_status = None
                student_comment = None
                percentage = None

                if student:
                    try:
                        grade = Grade.objects.get(assessment=item, student=student)
                        score = (
                            format_numeric_value(grade.score)
                            if grade.score is not None
                            else None
                        )
                        student_status = grade.status
                        student_comment = (
                            grade.comment if hasattr(grade, "comment") else None
                        )

                        # Calculate percentage if score exists
                        if grade.score is not None and item.max_score:
                            percentage = format_numeric_value(
                                float(grade.score) / float(item.max_score) * 100
                            )

                    except Grade.DoesNotExist:
                        pass

                formatted_items.append(
                    {
                        "id": item.id,
                        "active": item.active,
                        "name": item.name,
                        "assessment_type": (
                            {
                                "id": item.assessment_type.id,
                                "name": item.assessment_type.name,
                            }
                            if item.assessment_type
                            else None
                        ),
                        "marking_period": (
                            {
                                "id": item.marking_period.id,
                                "name": item.marking_period.name,
                                "short_name": item.marking_period.short_name,
                                "start_date": (
                                    item.marking_period.start_date.isoformat()
                                    if item.marking_period.start_date
                                    else None
                                ),
                                "end_date": (
                                    item.marking_period.end_date.isoformat()
                                    if item.marking_period.end_date
                                    else None
                                ),
                            }
                            if item.marking_period
                            else None
                        ),
                        "max_score": format_numeric_value(item.max_score),
                        "weight": format_numeric_value(item.weight),
                        "due_date": item.due_date,
                        "is_calculated": item.is_calculated,
                        "score": score,
                        "status": student_status,
                        "comment": student_comment,
                        "percentage": percentage,
                        "created_at": (
                            item.created_at.isoformat() if item.created_at else None
                        ),
                        "updated_at": (
                            item.updated_at.isoformat() if item.updated_at else None
                        ),
                    }
                )

            result.append(
                {
                    "id": gradebook.id,
                    "active": gradebook.active,
                    "name": gradebook.name,
                    "calculation_method": gradebook.calculation_method,
                    "created_at": (
                        gradebook.created_at.isoformat()
                        if gradebook.created_at
                        else None
                    ),
                    "updated_at": (
                        gradebook.updated_at.isoformat()
                        if gradebook.updated_at
                        else None
                    ),
                    "subject": {
                        "id": gradebook.section_subject.subject.id,
                        "name": gradebook.section_subject.subject.name,
                    },
                    "final_percentage": formatted_percentage,
                    "letter_grade": letter_grade,
                    "assessments": formatted_items,
                    # "approved_grades_count": gb_data.get("approved_grades_count", 0),
                    # "total_grades_count": gb_data.get("total_grades_count", 0),
                    # "calculated_grades_count": gb_data.get(
                    #     "calculated_grades_count", 0
                    # ),
                }
            )

        return result

    def get_total_average(self, obj):
        """Calculate overall average across all subjects"""
        gradebooks = obj.get("gradebooks", [])
        valid_percentages = []

        for gb_data in gradebooks:
            final_percentage = gb_data.get("final_percentage")

            if final_percentage is not None:
                try:
                    percentage_float = (
                        float(final_percentage)
                        if isinstance(final_percentage, str)
                        else float(final_percentage)
                    )
                    valid_percentages.append(percentage_float)
                except (ValueError, TypeError):
                    pass

        if valid_percentages:
            average = sum(valid_percentages) / len(valid_percentages)
            return format_numeric_value(average)
        return None

    def get_overall_letter_grade(self, obj):
        """Get overall letter grade based on total average"""
        total_average = self.get_total_average(obj)
        if total_average is None or total_average == 0:
            return "-"

        gradebooks = obj.get("gradebooks", [])
        if gradebooks:
            first_gradebook = gradebooks[0].get("gradebook")
            if first_gradebook:
                try:
                    return get_letter_grade(float(total_average))
                except AttributeError as e:
                    print(f"Debug - Error getting letter grade: {e}")
                    pass

        return "-"


class SectionFinalGradesOut(serializers.Serializer):
    """Serializer for all students' final grades in a section"""

    # section = serializers.SerializerMethodField()
    # subject = serializers.SerializerMethodField()
    # academic_year = serializers.SerializerMethodField()
    # gradebook = GradeBookOut(read_only=True)
    # students = StudentFinalGradeOut(many=True, read_only=True)
    class_average = serializers.SerializerMethodField()
    total_students = serializers.IntegerField(read_only=True)

    def get_class_average(self, obj):
        """Format class average properly"""
        average = obj.get("class_average")
        if average is not None:
            return format_numeric_value(average)
        return 0

    def get_section(self, obj):
        """Get section info"""
        from core.serializers import SectionSerializer

        return (
            SectionSerializer(obj.get("section")).data if obj.get("section") else None
        )

    def get_subject(self, obj):
        """Get subject info"""
        from core.serializers import SubjectSerializer

        sub = SubjectSerializer(obj.get("subject")).data if obj.get("subject") else None
        return {
            "id": sub.get("id"),
            "name": sub.get("name"),
        }

    def get_academic_year(self, obj):
        """Get academic year info"""
        from core.serializers import AcademicYearSerializer

        return (
            AcademicYearSerializer(obj.get("academic_year")).data
            if obj.get("academic_year")
            else None
        )

    def to_representation(self, instance):
        response = super().to_representation(instance)
        sub = self.get_subject(instance)
        response.update(sub)
        gb = instance.get("gradebook")
        gi = gb.assessments
        print(f"Debug - Grade items in gradebook {gb.id}: {gi}")
        response["gradebook"] = {
            "id": gb.id,
            "name": gb.name,
            "calculation_method": gb.calculation_method,
            "assessments": gi.count() if gi else 0,
        }
        return response


class GradeLetterOut(serializers.ModelSerializer):
    """Serializer for grade letters"""

    min_percentage = serializers.SerializerMethodField()
    max_percentage = serializers.SerializerMethodField()

    class Meta:
        model = GradeLetter
        fields = [
            "id",
            "active",
            "letter",
            "min_percentage",
            "max_percentage",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_min_percentage(self, obj):
        """Format min percentage properly"""
        return (
            format_numeric_value(obj.min_percentage)
            if obj.min_percentage is not None
            else None
        )

    def get_max_percentage(self, obj):
        """Format max percentage properly"""
        return (
            format_numeric_value(obj.max_percentage)
            if obj.max_percentage is not None
            else None
        )


class HonorCategoryOut(serializers.ModelSerializer):
    """Serializer for honor categories used on the dashboard."""

    min_average = serializers.SerializerMethodField()
    max_average = serializers.SerializerMethodField()

    class Meta:
        model = HonorCategory
        fields = [
            "id",
            "active",
            "label",
            "min_average",
            "max_average",
            "color",
            "icon",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_min_average(self, obj):
        return (
            format_numeric_value(obj.min_average)
            if obj.min_average is not None
            else None
        )

    def get_max_average(self, obj):
        return (
            format_numeric_value(obj.max_average)
            if obj.max_average is not None
            else None
        )


class SimplifiedSectionFinalGradesOut(serializers.Serializer):
    """
    Simplified serializer for section final grades - matches the proposed JSON structure
    """

    section = serializers.SerializerMethodField()
    grade_level = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()
    # semester = serializers.SerializerMethodField()
    # marking_period = serializers.SerializerMethodField()
    gradebook = serializers.SerializerMethodField()
    config = serializers.SerializerMethodField()
    students = serializers.SerializerMethodField()
    class_average = serializers.SerializerMethodField()
    total_students = serializers.IntegerField(read_only=True)

    def get_section(self, obj):
        """Get simplified section info"""
        section = obj.get("section")
        if not section:
            return None
        return {"id": section.id, "name": section.name}

    def get_grade_level(self, obj):
        """Get grade level info"""
        section = obj.get("section")
        if not section:
            return None
        return {"id": section.grade_level.id, "name": section.grade_level.name}

    def get_subject(self, obj):
        """Get subject info"""
        subject = obj.get("subject")
        if not subject:
            return None
        return {"id": subject.id, "name": subject.name}

    def get_academic_year(self, obj):
        """Get academic year info"""
        academic_year = obj.get("academic_year")
        if not academic_year:
            return None
        return {"id": academic_year.id, "name": academic_year.name}

    # def get_semester(self, obj):
    #     """Get semester info if available"""
    #     semester = obj.get('semester')
    #     if not semester:
    #         return None
    #     return {
    #         'id': semester.id,
    #         'name': semester.name
    #     }

    # def get_marking_period(self, obj):
    #     """Get marking period info if filtering by marking period"""
    #     marking_period = obj.get('marking_period')
    #     if not marking_period:
    #         return None
    #     return {
    #         'id': marking_period.id,
    #         'name': marking_period.name
    #     }

    def get_gradebook(self, obj):
        """Get simplified gradebook info"""
        gradebook = obj.get("gradebook")
        if not gradebook:
            return None
        return {
            "id": gradebook.id,
            "name": gradebook.name,
            "calculation_method": gradebook.calculation_method,
        }

    def get_config(self, obj):
        """Get grading configuration from settings"""
        # Skip config if we're in all_subjects mode (config is at top level)
        if self.context.get("skip_config", False):
            return None
        gradebook = obj.get("gradebook")
        if gradebook:
            return get_grading_config(gradebook)
        return None

    def get_students(self, obj):
        """Get students data with marking_periods array structure"""
        from .models import Grade, Assessment
        from academics.models import MarkingPeriod
        from collections import defaultdict

        students_data = obj.get("students", [])
        academic_year = obj.get("academic_year")
        gradebook = obj.get("gradebook")
        include_average = self.context.get("include_average", False)
        include_assessment = self.context.get("include_assessment", True)
        filter_marking_period = obj.get("marking_period")  # If filtering by specific MP

        result = []

        if not students_data or not academic_year:
            return result

        # Collect all student IDs
        student_ids = [
            student_data.get("student").id
            for student_data in students_data
            if student_data.get("student")
        ]

        # Get all marking periods for this academic year
        all_marking_periods = list(
            MarkingPeriod.objects.filter(semester__academic_year=academic_year)
            .select_related("semester")
            .order_by("semester__start_date", "start_date")
        )

        # If filtering by specific marking period, use only that one
        if filter_marking_period:
            all_marking_periods = [filter_marking_period]

        # Pre-fetch all assessments for all marking periods
        all_assessments_query = Assessment.objects.filter(
            gradebook=gradebook, marking_period__in=all_marking_periods
        ).select_related("assessment_type", "marking_period__semester")

        # Group assessments by marking period
        assessments_by_mp = defaultdict(list)
        for assessment in all_assessments_query:
            assessments_by_mp[assessment.marking_period_id].append(assessment)

        # Pre-fetch all grades for all students and assessments
        all_assessment_ids = [a.id for a in all_assessments_query]
        grades_dict = {}
        if student_ids and all_assessment_ids:
            grades = Grade.objects.filter(
                student_id__in=student_ids, assessment_id__in=all_assessment_ids
            ).select_related("student", "assessment")

            # Create lookup: {(student_id, assessment_id): grade}
            for grade in grades:
                key = (grade.student_id, grade.assessment_id)
                grades_dict[key] = grade

        # Pre-fetch rankings
        final_rank_map = {}
        mp_rank_maps = {}

        from grading.services.ranking import RankingService

        subject = obj.get("subject")
        section = obj.get("section")

        if subject and section and academic_year:
            # Final Rank
            final_rankings = RankingService.get_subject_rankings(
                subject_id=subject.id,
                academic_year_id=academic_year.id,
                scope_type="section",
                scope_id=section.id,
            )
            final_rank_map = {str(r["student"].id): r for r in final_rankings}

            # MP Rankings
            for mp in all_marking_periods:
                mp_ranks = RankingService.get_subject_rankings(
                    subject_id=subject.id,
                    academic_year_id=academic_year.id,
                    scope_type="section",
                    scope_id=section.id,
                    marking_period_id=mp.id,
                )
                mp_rank_maps[mp.id] = {str(r["student"].id): r for r in mp_ranks}

        # Build student results
        for student_data in students_data:
            student = student_data.get("student")
            if not student:
                continue

            # Calculate semester averages and final average for this student
            semester_percentages = defaultdict(list)
            all_percentages = []

            # Build marking_periods array
            marking_periods = []
            for mp in all_marking_periods:
                assessments_for_mp = assessments_by_mp.get(mp.id, [])

                # Calculate final percentage for this marking period
                mp_percentages = []
                assessments_output = []
                mp_grade_ids = []  # Track grade IDs for this marking period
                needs_correction = False  # Track if any grade needs correction

                for assessment in assessments_for_mp:
                    student_grade = grades_dict.get((student.id, assessment.id))

                    score = student_grade.score if student_grade else None
                    status = student_grade.status if student_grade else None
                    comment = student_grade.comment if student_grade else None

                    # Track grade IDs and correction status
                    if student_grade:
                        mp_grade_ids.append(student_grade.id)
                        if getattr(student_grade, 'needs_correction', False):
                            needs_correction = True

                    # Calculate percentage if score exists
                    percentage = None
                    if score is not None and assessment.max_score:
                        try:
                            percentage = round(
                                (float(score) / float(assessment.max_score)) * 100, 2
                            )
                            mp_percentages.append(percentage)
                        except (ValueError, ZeroDivisionError):
                            pass

                    if include_assessment:
                        assessments_output.append(
                            {
                                "id": assessment.id,
                                "name": assessment.name,
                                "assessment_type": (
                                    {
                                        "id": assessment.assessment_type.id,
                                        "name": assessment.assessment_type.name,
                                    }
                                    if assessment.assessment_type
                                    else None
                                ),
                                "max_score": format_numeric_value(assessment.max_score),
                                "weight": format_numeric_value(assessment.weight),
                                "due_date": assessment.due_date,
                                "is_calculated": assessment.is_calculated,
                                "score": format_numeric_value(score),
                                "status": status,
                                "comment": comment,
                                "grade_id": student_grade.id if student_grade else None,
                                "percentage": format_numeric_value(percentage),
                            }
                        )

                # Calculate final percentage for this marking period
                final_percentage = 0
                if mp_percentages:
                    final_percentage = sum(mp_percentages) / len(mp_percentages)
                    all_percentages.extend(mp_percentages)
                    if mp.semester:
                        semester_percentages[mp.semester.id].append(
                            {"semester": mp.semester, "percentage": final_percentage}
                        )

                # Get letter grade
                letter_grade = "-"
                if final_percentage and gradebook:
                    try:
                        letter_grade = get_letter_grade(final_percentage)
                    except AttributeError:
                        pass

                mp_data = {
                    "id": mp.id,
                    "name": mp.name,
                    "short_name": mp.short_name,
                    "start_date": mp.start_date.isoformat() if mp.start_date else None,
                    "end_date": mp.end_date.isoformat() if mp.end_date else None,
                    "final_percentage": format_numeric_value(final_percentage),
                    "letter_grade": letter_grade,
                    "status": status if assessments_for_mp else None,
                    "needs_correction": needs_correction,
                }

                # Include history summary for grades in this marking period
                if mp_grade_ids:
                    from grading.models import GradeHistory
                    
                    history_records = GradeHistory.objects.filter(
                        grade_id__in=mp_grade_ids
                    ).select_related('changed_by').order_by('-created_at')[:5]  # Last 5 changes
                    
                    mp_data["history"] = [{
                        "id": str(h.id),
                        "change_type": h.change_type,
                        "old_score": str(h.old_score) if h.old_score else None,
                        "new_score": str(h.new_score) if h.new_score else None,
                        "old_status": h.old_status,
                        "new_status": h.new_status,
                        "change_reason": h.change_reason,
                        "changed_by": {
                            "id": str(h.changed_by.id),
                            "name": h.changed_by.get_full_name() or h.changed_by.username,
                        } if h.changed_by else None,
                        "changed_at": h.created_at.isoformat(),
                        "grade_id": str(h.grade_id),
                    } for h in history_records]
                    mp_data["history_count"] = history_records.count() if history_records else 0
                else:
                    mp_data["history"] = []
                    mp_data["history_count"] = 0

                if include_assessment:
                    mp_data["assessments"] = assessments_output

                if mp.semester:
                    mp_data["semester"] = {
                        "id": mp.semester.id,
                        "name": mp.semester.name,
                    }

                marking_periods.append(mp_data)

            # Build averages object
            student_result = {
                "id": student.id,
                "id_number": student.id_number,
                "full_name": student.get_full_name(),
            }

            if include_average:
                # Calculate semester averages
                semester_averages = []
                for sem_id, sem_data in semester_percentages.items():
                    sem_obj = sem_data[0]["semester"]
                    sem_percs = [d["percentage"] for d in sem_data]
                    avg = sum(sem_percs) / len(sem_percs) if sem_percs else 0
                    semester_averages.append(
                        {
                            "id": sem_obj.id,
                            "name": sem_obj.name,
                            "average": format_numeric_value(avg),
                        }
                    )

                # Calculate final average
                final_average = 0
                if all_percentages:
                    final_average = sum(all_percentages) / len(all_percentages)

                student_result["averages"] = {
                    "semester_averages": semester_averages,
                    "final_average": format_numeric_value(final_average),
                }

            # If filtering by specific marking period, return as object instead of array
            if filter_marking_period:
                student_result["marking_period"] = (
                    marking_periods[0] if marking_periods else None
                )
            else:
                student_result["marking_periods"] = marking_periods

            # Add final rank
            if include_average and "averages" in student_result:
                rank_data = final_rank_map.get(str(student.id))
                if rank_data:
                    student_result["averages"]["rank"] = rank_data["rank"]
                    student_result["averages"][
                        "rank_label"
                    ] = f"{rank_data['rank']}/{len(final_rankings)}"

            # Add MP ranks
            if filter_marking_period:
                if (
                    "marking_period" in student_result
                    and student_result["marking_period"]
                ):
                    mp_id = student_result["marking_period"]["id"]
                    rank_map = mp_rank_maps.get(mp_id)
                    if rank_map:
                        rank_data = rank_map.get(str(student.id))
                        if rank_data:
                            student_result["marking_period"]["rank"] = rank_data["rank"]
                            student_result["marking_period"][
                                "rank_label"
                            ] = f"{rank_data['rank']}/{len(rank_map)}"
            else:
                # Array
                for mp_data in student_result.get("marking_periods", []):
                    mp_id = mp_data["id"]
                    rank_map = mp_rank_maps.get(mp_id)
                    if rank_map:
                        rank_data = rank_map.get(str(student.id))
                        if rank_data:
                            mp_data["rank"] = rank_data["rank"]
                            mp_data["rank_label"] = (
                                f"{rank_data['rank']}/{len(rank_map)}"
                            )

            result.append(student_result)

        return result

    def get_class_average(self, obj):
        """Format class average properly"""
        average = obj.get("class_average")
        if average is not None:
            return format_numeric_value(average)
        return 0

    def to_representation(self, instance):
        response = super().to_representation(instance)
        if self.context.get("skip_config", False):
            response.pop("config", None)
        return response


class StudentMarkingPeriodGradesOut(serializers.Serializer):
    """
    Serializer for student grades filtered by marking period and academic year
    """

    student = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()
    semester = serializers.SerializerMethodField()
    marking_period = serializers.SerializerMethodField()
    data_by = serializers.CharField()
    config = serializers.SerializerMethodField()
    total_subjects = serializers.IntegerField()
    subjects_with_grades = serializers.IntegerField()
    overall_average = serializers.SerializerMethodField()
    gradebooks = serializers.SerializerMethodField()
    ranking = serializers.SerializerMethodField()

    def get_ranking(self, obj):
        """Get ranking for this student in this marking period"""
        from grading.services.ranking import RankingService

        student = obj.get("student")
        academic_year = obj.get("academic_year")
        marking_period = obj.get("marking_period")

        if not student or not academic_year or not marking_period:
            return None

        # We need to find the section from gradebooks
        gradebooks_data = obj.get("gradebooks", [])
        section = None
        if gradebooks_data:
            # Assuming all gradebooks belong to same section for a student in a year
            # gradebook object is in gradebook_data['gradebook']
            section = gradebooks_data[0]["gradebook"].section

        if not section:
            return None

        # Get overall rank within the section for this marking period
        section_rank = RankingService.get_student_overall_rank(
            student_id=student.id,
            academic_year_id=academic_year.id,
            scope_type="section",
            scope_id=section.id,
            marking_period_id=marking_period.id,
        )

        # Get overall rank within the grade level for this marking period
        grade_level_rank = None
        if hasattr(section, "grade_level") and section.grade_level:
            grade_level_rank = RankingService.get_student_overall_rank(
                student_id=student.id,
                academic_year_id=academic_year.id,
                scope_type="grade_level",
                scope_id=section.grade_level.id,
                marking_period_id=marking_period.id,
            )

        return {"section": section_rank, "grade_level": grade_level_rank}

    def get_student(self, obj):
        student = obj["student"]
        return {
            "id": student.id,
            "id_number": student.id_number,
            "name": student.get_full_name(),
        }

    def get_academic_year(self, obj):
        return {"id": obj["academic_year"].id, "name": obj["academic_year"].name}

    def get_semester(self, obj):
        semester = obj.get("semester")
        return {"id": semester.id, "name": semester.name} if semester else None

    def get_marking_period(self, obj):
        marking_period = obj.get("marking_period")
        return (
            {
                "id": marking_period.id,
                "name": marking_period.name,
                "short_name": marking_period.short_name,
                "start_date": (
                    marking_period.start_date.isoformat()
                    if marking_period.start_date
                    else None
                ),
                "end_date": (
                    marking_period.end_date.isoformat()
                    if marking_period.end_date
                    else None
                ),
            }
            if marking_period
            else None
        )

    def get_overall_average(self, obj):
        average = obj.get("overall_average")
        if average is not None:
            return format_numeric_value(average)
        return None

    def get_config(self, obj):
        gradebooks_data = obj.get("gradebooks", [])
        if gradebooks_data:
            first_gradebook = gradebooks_data[0].get("gradebook")
            return get_grading_config(first_gradebook)
        return None

    def get_gradebooks(self, obj):
        gradebooks_data = obj["gradebooks"]
        serialized_gradebooks = []

        for gradebook_data in gradebooks_data:
            gradebook = gradebook_data["gradebook"]
            student = gradebook_data["student"]
            final_percentage = gradebook_data.get("final_percentage")
            marking_period = gradebook_data.get("marking_period")

            # Get letter grade
            letter_grade = None
            if final_percentage is not None:
                letter_grade = get_letter_grade(final_percentage)

            serialized_data = {
                "gradebook": {
                    "id": gradebook.id,
                    "name": gradebook.name,
                    "calculation_method": gradebook.calculation_method,
                },
                "subject": {
                    "id": gradebook.section_subject.subject.id,
                    "name": gradebook.section_subject.subject.name,
                },
                "final_percentage": format_numeric_value(final_percentage),
                "letter_grade": letter_grade,
                # 'approved_grades_count': gradebook_data['approved_grades_count'],
                # 'total_grades_count': gradebook_data['total_grades_count'],
                # 'calculated_grades_count': gradebook_data['calculated_grades_count'],
                "grade_status": gradebook_data.get("grade_status"),
                "grade_status_display": gradebook_data.get("grade_status_display"),
            }

            serialized_gradebooks.append(serialized_data)

        return serialized_gradebooks


# ============================================================================
# Default Assessment Template Serializers
# ============================================================================


class DefaultAssessmentTemplateOut(serializers.ModelSerializer):
    """Serializer for DefaultAssessmentTemplate (read-only)"""

    assessment_type = serializers.SerializerMethodField()
    target_display = serializers.SerializerMethodField()

    class Meta:
        model = DefaultAssessmentTemplate
        fields = [
            "id",
            "active",
            "name",
            "assessment_type",
            "max_score",
            "weight",
            "is_calculated",
            "order",
            "description",
            "is_active",
            "target",
            "target_display",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_assessment_type(self, obj):
        return {
            "id": obj.assessment_type.id,
            "name": obj.assessment_type.name,
        }

    def get_target_display(self, obj):
        """Get human-readable target display"""
        return dict(DefaultAssessmentTemplate.ASSESSMENT_TARGET_CHOICES).get(
            obj.target, obj.target
        )

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["max_score"] = format_numeric_value(instance.max_score)
        response["weight"] = format_numeric_value(instance.weight)
        return response


class DefaultAssessmentTemplateIn(serializers.ModelSerializer):
    """Serializer for creating/updating DefaultAssessmentTemplate"""

    class Meta:
        model = DefaultAssessmentTemplate
        fields = [
            "name",
            "assessment_type",
            "max_score",
            "weight",
            "is_calculated",
            "order",
            "description",
            "is_active",
            "target",
        ]


class AssessmentGenerationPreviewOut(serializers.Serializer):
    """Serializer for preview of what assessments would be generated"""

    will_create = serializers.ListField(child=serializers.DictField())
    already_exists = serializers.ListField(child=serializers.DictField())
    skipped_by_target_mismatch = serializers.ListField(child=serializers.DictField())

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["summary"] = {
            "total_to_create": len(instance.get("will_create", [])),
            "total_existing": len(instance.get("already_exists", [])),
            "total_skipped": len(instance.get("skipped_by_target_mismatch", [])),
        }
        return response


class BulkAssessmentGenerationResultOut(serializers.Serializer):
    """Serializer for bulk generation results"""

    gradebooks_processed = serializers.IntegerField()
    assessments_created = serializers.IntegerField()
    single_entry_gradebooks = serializers.IntegerField(required=False)
    multiple_entry_gradebooks = serializers.IntegerField(required=False)
    gradebooks_with_errors = serializers.ListField(child=serializers.DictField())

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["success"] = len(instance.get("gradebooks_with_errors", [])) == 0
        response["error_count"] = len(instance.get("gradebooks_with_errors", []))
        return response


class UnifiedStudentFinalGradesOut(serializers.Serializer):
    """
    Unified serializer for student final grades across all query modes.
    Supports filtering by subject, marking period, or both.
    """

    id = serializers.UUIDField(source="student.id")
    id_number = serializers.CharField(source="student.id_number")
    full_name = serializers.SerializerMethodField()
    section = serializers.SerializerMethodField()
    grade_level = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()
    config = serializers.SerializerMethodField()
    gradebooks = serializers.SerializerMethodField()
    overall_averages = serializers.SerializerMethodField()
    total_gradebooks = serializers.SerializerMethodField()
    ranking = serializers.SerializerMethodField()

    def get_ranking(self, obj):
        """Get student ranking information"""
        from grading.services.ranking import RankingService

        student = obj.get("student")
        academic_year = obj.get("academic_year")
        section = obj.get("section")

        if not student or not academic_year or not section:
            return None

        # Get overall rank within the section
        section_rank = RankingService.get_student_overall_rank(
            student_id=student.id,
            academic_year_id=academic_year.id,
            scope_type="section",
            scope_id=section.id,
        )

        # Get overall rank within the grade level
        grade_level_rank = None
        if hasattr(section, "grade_level") and section.grade_level:
            grade_level_rank = RankingService.get_student_overall_rank(
                student_id=student.id,
                academic_year_id=academic_year.id,
                scope_type="grade_level",
                scope_id=section.grade_level.id,
            )

        return {"section": section_rank, "grade_level": grade_level_rank}

    def get_full_name(self, obj):
        student = obj.get("student")
        return student.get_full_name() if student else None

    def get_section(self, obj):
        section = obj.get("section")
        if not section:
            return None
        return {"id": section.id, "name": section.name}

    def get_grade_level(self, obj):
        grade_level = obj.get("grade_level")
        if not grade_level:
            return None
        return {"id": grade_level.id, "name": grade_level.name}

    def get_academic_year(self, obj):
        academic_year = obj.get("academic_year")
        if not academic_year:
            return None
        return {"id": academic_year.id, "name": academic_year.name}

    def get_config(self, obj):
        """Get grading configuration from first gradebook"""
        gradebooks_data = obj.get("gradebooks_data", [])
        if gradebooks_data:
            first_gradebook_data = gradebooks_data[0]
            gradebook = first_gradebook_data.get("gradebook")
            if gradebook:
                return get_grading_config(gradebook)
        return None

    def get_total_gradebooks(self, obj):
        return len(obj.get("gradebooks_data", []))

    def get_gradebooks(self, obj):
        """
        Build gradebooks array. Returns object if single gradebook, array otherwise.
        """
        from .models import Grade, Assessment
        from academics.models import MarkingPeriod
        from collections import defaultdict

        gradebooks_data = obj.get("gradebooks_data", [])
        student = obj.get("student")
        academic_year = obj.get("academic_year")
        include_average = self.context.get("include_average", False)
        include_assessment = self.context.get("include_assessment", True)
        filter_marking_period = obj.get("filter_marking_period")
        single_gradebook = obj.get("single_gradebook", False)

        if not gradebooks_data or not student or not academic_year:
            return [] if not single_gradebook else None

        result = []

        for gradebook_data in gradebooks_data:
            gradebook = gradebook_data.get("gradebook")
            subject = gradebook.subject if gradebook else None

            if not gradebook:
                continue

            # Get all marking periods for this academic year
            all_marking_periods = list(
                MarkingPeriod.objects.filter(semester__academic_year=academic_year)
                .select_related("semester")
                .order_by("semester__start_date", "start_date")
            )

            # The selected marking period controls the visible score payload,
            # while gradebook averages remain cumulative across the academic year.

            # Pre-fetch all grades for this student and gradebook
            grades = Grade.objects.filter(
                student=student, assessment__gradebook=gradebook
            ).select_related(
                "assessment__marking_period", "assessment__assessment_type"
            )

            # Build lookup dictionaries
            grades_dict = defaultdict(list)
            for grade in grades:
                if grade.assessment and grade.assessment.marking_period:
                    grades_dict[grade.assessment.marking_period.id].append(grade)

            # Pre-fetch all assessments for this gradebook
            assessments_query = Assessment.objects.filter(
                gradebook=gradebook
            ).select_related(
                "marking_period", "assessment_type", "marking_period__semester"
            )

            assessments_by_mp = defaultdict(list)
            for assessment in assessments_query:
                if assessment.marking_period:
                    assessments_by_mp[assessment.marking_period.id].append(assessment)

            # Build marking_periods array
            marking_periods_list = []
            semester_totals = defaultdict(lambda: {"sum": 0, "count": 0})

            for mp in all_marking_periods:
                mp_grades = grades_dict.get(mp.id, [])

                # Calculate final percentage for this marking period
                # Import the calculation function
                from grading.views.final_grades import (
                    calculate_marking_period_percentage,
                )

                final_percentage = None
                letter_grade = "-"
                status = None

                # Calculate the final percentage using the gradebook's calculation method
                if gradebook and student:
                    final_percentage = calculate_marking_period_percentage(
                        gradebook, student, mp, status=self.context.get("status", "any")
                    )

                    # Get letter grade if we have a percentage
                    if final_percentage is not None:
                        try:
                            letter_grade = get_letter_grade(float(final_percentage))
                        except:
                            pass

                    # Get status from any calculated grade in this marking period
                    for grade in mp_grades:
                        if (
                            grade.assessment
                            and grade.assessment.is_calculated
                            and grade.status
                        ):
                            status = grade.status
                            break

                # Get subject rank for this marking period
                subject_rank = None
                if gradebook and student:
                    from grading.services.ranking import RankingService

                    subject_rank = RankingService.get_student_subject_rank(
                        student_id=student.id,
                        subject_id=gradebook.section_subject.subject.id,
                        academic_year_id=academic_year.id,
                        scope_type="section",
                        scope_id=gradebook.section.id,
                        marking_period_id=mp.id,
                    )

                # Build marking period data
                mp_data = {
                    "id": mp.id,
                    "name": mp.name,
                    "short_name": mp.short_name,
                    "start_date": mp.start_date.isoformat() if mp.start_date else None,
                    "end_date": mp.end_date.isoformat() if mp.end_date else None,
                    "final_percentage": (
                        format_numeric_value(final_percentage)
                        if final_percentage is not None
                        else None
                    ),
                    "letter_grade": letter_grade,
                    "status": status,
                    "semester": {"id": mp.semester.id, "name": mp.semester.name},
                    "rank": subject_rank,
                }

                # Add assessments if requested
                if include_assessment:
                    mp_assessments = assessments_by_mp.get(mp.id, [])
                    formatted_assessments = []

                    for assessment in mp_assessments:
                        # Find the grade for this assessment
                        grade_obj = next(
                            (g for g in mp_grades if g.assessment_id == assessment.id),
                            None,
                        )

                        assessment_data = {
                            "id": assessment.id,
                            "name": assessment.name,
                            "assessment_type": (
                                {
                                    "id": assessment.assessment_type.id,
                                    "name": assessment.assessment_type.name,
                                }
                                if assessment.assessment_type
                                else None
                            ),
                            "max_score": format_numeric_value(assessment.max_score),
                            "weight": format_numeric_value(assessment.weight),
                            "due_date": (
                                assessment.due_date.isoformat()
                                if assessment.due_date
                                else None
                            ),
                            "is_calculated": assessment.is_calculated,
                            "score": (
                                format_numeric_value(grade_obj.score)
                                if grade_obj and grade_obj.score is not None
                                else None
                            ),
                            "status": grade_obj.status if grade_obj else None,
                            "comment": grade_obj.comment if grade_obj else None,
                            "grade_id": str(grade_obj.id) if grade_obj else None,
                            "percentage": (
                                format_numeric_value(
                                    (grade_obj.score / assessment.max_score) * 100
                                )
                                if grade_obj
                                and grade_obj.score is not None
                                and assessment.max_score
                                else None
                            ),
                        }
                        formatted_assessments.append(assessment_data)

                    mp_data["assessments"] = formatted_assessments

                if not filter_marking_period or mp.id == filter_marking_period.id:
                    marking_periods_list.append(mp_data)

                if final_percentage is not None:
                    semester_totals[mp.semester.id]["sum"] += float(final_percentage)
                    semester_totals[mp.semester.id]["count"] += 1

            # Build gradebook result data
            gradebook_result = {
                "id": gradebook.id,
                "name": gradebook.name,
                "calculation_method": gradebook.calculation_method,
                "subject": (
                    {"id": subject.id, "name": subject.name} if subject else None
                ),
            }

            # Add averages if requested
            if include_average:
                semester_averages = []
                total_sum = 0
                total_count = 0

                for mp in all_marking_periods:
                    semester_id = mp.semester.id
                    semester_data = semester_totals.get(semester_id)

                    if semester_data and semester_data["count"] > 0:
                        avg = semester_data["sum"] / semester_data["count"]

                        # Check if we already added this semester
                        if not any(s["id"] == semester_id for s in semester_averages):
                            semester_averages.append(
                                {
                                    "id": semester_id,
                                    "name": mp.semester.name,
                                    "average": format_numeric_value(avg),
                                }
                            )
                            total_sum += avg
                            total_count += 1

                final_average = (
                    format_numeric_value(total_sum / total_count)
                    if total_count > 0
                    else None
                )

                gradebook_result["averages"] = {
                    "semester_averages": semester_averages,
                    "final_average": final_average,
                }

            # Add marking_periods (as object if single, array otherwise)
            if filter_marking_period:
                # Single marking period - return as object
                gradebook_result["marking_period"] = (
                    marking_periods_list[0] if marking_periods_list else None
                )
            else:
                # Multiple marking periods - return as array
                gradebook_result["marking_periods"] = marking_periods_list

            result.append(gradebook_result)

        # Return object if single gradebook, array otherwise
        if single_gradebook:
            return result[0] if result else None
        return result

    def get_overall_averages(self, obj):
        """Calculate overall averages across all gradebooks for the academic year"""
        include_average = self.context.get("include_average", False)
        if not include_average:
            return None

        gradebooks_data = obj.get("gradebooks_data", [])
        student = obj.get("student")
        academic_year = obj.get("academic_year")
        filter_marking_period = obj.get("filter_marking_period")

        if not gradebooks_data or not student or not academic_year:
            return {"semester_averages": [], "final_average": None}

        # Extract gradebooks from gradebooks_data
        gradebooks = [
            gb_data.get("gradebook")
            for gb_data in gradebooks_data
            if gb_data.get("gradebook")
        ]

        # Use the standardized calculation utility
        from grading.utils import calculate_student_overall_average

        result = calculate_student_overall_average(
            student=student,
            academic_year=academic_year,
            gradebooks=gradebooks,
            status=self.context.get("status", "any"),
        )

        # Return None for final_average if it's 0 and there are no semester averages
        # This indicates no grades available rather than an actual zero average
        final_average = result["final_average"]
        if final_average == 0 and not result["semester_averages"]:
            final_average = None

        # Format the result for the API response
        return {
            "semester_averages": result["semester_averages"],
            "final_average": final_average,
        }

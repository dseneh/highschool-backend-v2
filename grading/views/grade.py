from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import GradebookAccessPolicy
from rest_framework.exceptions import NotFound

from academics.models import MarkingPeriod
from common.utils import get_object_by_uuid_or_fields
from grading.utils import (
    can_edit_grade_status,
    is_valid_transition,
    get_workflow_settings,
    paginate_qs,
    parse_decimal,
)

from grading.models import GradeBook, Assessment, Grade
from grading.serializers import GradeOut
from grading.services.authorization import (
    enforce_teacher_grade_access,
    get_teacher_allowed_section_ids_for_subject,
)

from students.models import Student


class GradeListCreateView(APIView):
    permission_classes = [GradebookAccessPolicy]
    """
    GET  /grades/?assessment=&student=&academic_year=&section=&subject=
    POST /grades/  (manual upsert by (assessment, enrollment))
      Required: assessment, score, and either enrollment OR student
      Optional: status (defaults to "draft")
    """

    def get_object(self, pk):
        try:
            return (
                Assessment.objects.select_related(
                    "gradebook", "assessment_type", "marking_period"
                )
                .only(
                    "id",
                    "active",
                    "gradebook",
                    "assessment_type",
                    "marking_period",
                    "name",
                    "max_score",
                    "weight",
                    "due_date",
                    "created_at",
                    "updated_at",
                )
                .get(pk=pk)
            )
        except Assessment.DoesNotExist:
            raise NotFound("This assessment does not exist.")

    def get(self, request, assessment_id):
        assessment = self.get_object(assessment_id)
        print("DEBUG: assessment", assessment.id)

        # Enforce teacher scope for grade listing by assessment.
        enforce_teacher_grade_access(
            request.user,
            assessment.gradebook.section_id,
            assessment.gradebook.subject_id,
        )

        qs = assessment.grades.select_related(
            "assessment", "student", "section", "subject"
        ).only(
            "id",
            "active",
            "assessment",
            "student",
            "section",
            "subject",
            "score",
            "status",
            "created_at",
            "updated_at",
        )
        student = request.query_params.get("student")
        if student:
            f = Q(student_id=student) | Q(student__id_number=student)
            qs = qs.filter(f)

        # if gi := request.query_params.get("assessment"): qs = qs.filter(assessment_id=gi)
        # if st := request.query_params.get("student"): qs = qs.filter(student_id=st)
        # if ay := request.query_params.get("academic_year"): qs = qs.filter(academic_year_id=ay)
        # if sec := request.query_params.get("section"): qs = qs.filter(section_id=sec)
        # if sub := request.query_params.get("subject"): qs = qs.filter(subject_id=sub)

        # page, meta = paginate_qs(qs, request)
        # return Response({"meta": meta, "results": GradeOut(page, many=True).data})
        return Response(GradeOut(qs, many=True).data)

    # 💥 COMMENTED OUT FOR NOW - grade creation should be done from the creation of a grade item automatically
    # @transaction.atomic
    # def post(self, request):
    #     assessment_id = request.data.get("assessment")
    #     enrollment_id = request.data.get("enrollment")
    #     student_id = request.data.get("student")
    #     raw_score = request.data.get("score")
    #     status_raw = (request.data.get("status") or Grade.Status.DRAFT).lower()

    #     if not assessment_id or raw_score is None or not (enrollment_id or student_id):
    #         return Response({"detail": "assessment, score and (enrollment or student) are required."}, status=400)
    #     if status_raw not in dict(Grade.Status.choices):
    #         return Response({"detail": "Invalid status."}, status=400)

    #     item = get_object_or_404(Assessment.objects.select_related("gradebook", "gradebook__section_subject"), pk=assessment_id)
    #     gb = item.gradebook

    #     try:
    #         score = parse_decimal(raw_score, "score")
    #     except ValueError as e:
    #         return Response({"detail": str(e)}, status=400)
    #     if score < 0:
    #         return Response({"detail": "score cannot be negative."}, status=400)
    #     if item.max_score is not None and score > item.max_score:
    #         return Response({"detail": "score cannot exceed max_score."}, status=400)

    #     # Resolve/validate enrollment
    #     if not enrollment_id:
    #         if not student_id:
    #             return Response({"detail": "Provide enrollment or student."}, status=400)
    #         enrollment = resolve_enrollment_for_gradebook(student_id=student_id, gradebook=gb)
    #         if not enrollment:
    #             return Response({"detail": "No matching enrollment for this year/section."}, status=400)
    #         enrollment_id = enrollment.id
    #     else:
    #         enrollment = get_object_or_404(Enrollment.objects.select_related("student", "section"), pk=enrollment_id)
    #         if enrollment.academic_year_id != gb.academic_year_id:
    #             return Response({"detail": "Enrollment academic year mismatch with GradeBook."}, status=400)
    #         ss = gb.section_subject
    #         if hasattr(ss, "section_id") and enrollment.section_id != ss.section_id:
    #             return Response({"detail": "Enrollment section mismatch with GradeBook SectionSubject."}, status=400)
    #         if student_id and str(enrollment.student_id) != str(student_id):
    #             return Response({"detail": "student does not match enrollment."}, status=400)

    #     # Upsert (assessment, enrollment)
    #     obj, created = Grade.objects.select_for_update().get_or_create(
    #         assessment_id=item.id, enrollment_id=enrollment_id,
    #         defaults={
    #             "score": score,
    #             "status": status_raw,
    #             "student_id": enrollment.student_id,  # eager denorm
    #             "created_by": request.user, "updated_by": request.user,
    #         }
    #     )
    #     if not created:
    #         if not can_edit_grade_status(obj.status):
    #             return Response({"detail": f"Grade not editable in '{obj.status}' status."}, status=409)
    #         obj.score = score
    #         obj.status = status_raw
    #         obj.updated_by = request.user
    #         obj.save(update_fields=["score", "status", "updated_by", "updated_at"])
    #     else:
    #         # ensure denorms (academic_year/section/subject) are populated via save()
    #         obj.save()

    #     return Response(GradeOut(obj).data, status=201 if created else 200)


def get_object(pk):
    try:
        return (
            Grade.objects.select_related("assessment", "student", "enrollment")
            .only(
                "id",
                "active",
                "assessment",
                "enrollment",
                "student",
                "score",
                "status",
                "created_at",
                "updated_at",
                "academic_year",
                "section",
                "subject",
            )
            .get(pk=pk)
        )
    except Grade.DoesNotExist:
        raise NotFound("This grade does not exist.")


class GradeDetailView(APIView):
    permission_classes = [GradebookAccessPolicy]
    """
    GET    /grades/<id>/
    PUT    /grades/<id>/   (update score only when status=draft)
    DELETE /grades/<id>/
    """

    def get(self, request, pk):
        grade = get_object(pk)
        enforce_teacher_grade_access(request.user, grade.section_id, grade.subject_id)
        return Response(GradeOut(grade).data)

    @transaction.atomic
    def put(self, request, pk):
        grade = get_object(pk)

        # Teachers can only edit grades for their assigned section/subject.
        enforce_teacher_grade_access(request.user, grade.section_id, grade.subject_id)

        score = request.data.get("score")

        if not can_edit_grade_status(grade.status):
            return Response(
                {"detail": f"Grade not editable in '{grade.status}' status."},
                status=409,
            )

        if not str(score):
            return Response({"detail": "score is required."}, status=400)

        try:
            score = parse_decimal(score, "score")
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        if score < 0:
            return Response({"detail": "score cannot be negative."}, status=400)

        max_score = grade.assessment.max_score
        if max_score is not None and score > max_score:
            return Response(
                {"detail": f"score cannot exceed of {max_score}."}, status=400
            )

        # allowed_fields = ["score"]
        grade.score = score
        grade.status = Grade.Status.DRAFT  # reset to draft on manual edit
        grade.updated_by = request.user
        grade.save(update_fields=["score", "status", "updated_by", "updated_at"])
        return Response(GradeOut(grade).data)

    # @transaction.atomic
    # def delete(self, request, pk):
    #     grade = get_object_or_404(Grade, pk=pk)
    #     grade.delete()
    #     return Response(status=204)


def run_validation_checks(request, grade=None):
    target = request.data.get("status")

    if target not in dict(Grade.Status.choices):
        raise ValidationError(
            {"detail": f"Provided status value of '{target}' is invalid."}
        )

    if grade:
        # Get workflow settings for validation
        workflow_settings = get_workflow_settings()
        require_review = workflow_settings["require_grade_review"]
        require_approval = workflow_settings["require_grade_approval"]
        
        if not is_valid_transition(grade.status, target, require_review, require_approval):
            raise ValidationError(
                {"detail": f"Invalid transition {grade.status} → {target}."}
            )


class GradeStatusTransitionView(APIView):
    permission_classes = [GradebookAccessPolicy]
    """
    PUT /grades/<id>/status/  { "status": "pending|reviewed|approved|draft", "targeted_status": "draft" (optional) }
    """

    # @transaction.atomic
    def put(self, request, pk):
        target = request.data.get("status")
        targeted_status = request.data.get("targeted_status")

        # if target not in dict(Grade.Status.choices):
        #     return Response({"detail": "Invalid status."}, status=400)

        # if not is_valid_transition(grade.status, target):
        #     return Response({"detail": f"Invalid transition {grade.status} → {target}."}, status=409)

        # required_permission = None

        # if target == GradeStatus.APPROVED:
        #     required_permission =
        # elif target == GradeStatus.REJECTED:
        #     required_permission =
        # elif target == GradeStatus.SUBMITTED:
        #     required_permission =
        # elif target == GradeStatus.REVIEWED:
        #     required_permission =

        grade = get_object(pk)

        # Teachers can only transition grades for assigned section/subject.
        enforce_teacher_grade_access(request.user, grade.section_id, grade.subject_id)

        # Check if targeted_status filter applies
        if targeted_status is not None and grade.status != targeted_status:
            return Response(
                {
                    "detail": f"Grade status is '{grade.status}', not '{targeted_status}'. No update performed."
                },
                status=400,
            )

        run_validation_checks(request, grade)

        if grade.status == Grade.Status.APPROVED:
            return Response({"detail": "Approved grades are locked."}, status=409)

        grade.status = target
        grade.updated_by = request.user
        grade.save(update_fields=["status", "updated_by", "updated_at"])
        return Response(GradeOut(grade).data)


class SectionGradeStatusTransitionView(APIView):
    permission_classes = [GradebookAccessPolicy]
    """
    PUT /sections/<section_id>/grades/status/
    { "status": "pending|reviewed|approved|draft", "targeted_status": "draft" (optional) }

    Query params: marking_period, subject
    """

    @transaction.atomic
    def put(self, request, section_id):
        target = request.data.get("status")
        targeted_status = request.data.get("targeted_status")
        marking_period_id = request.query_params.get("marking_period")
        subject_id = request.query_params.get("subject")

        if target not in dict(Grade.Status.choices):
            return Response({"detail": f"Status {target} is invalid."}, status=400)

        if not marking_period_id:
            return Response(
                {"detail": "marking_period must be added to the request query params."},
                status=400,
            )

        if not subject_id:
            return Response(
                {"detail": "subject must be added to the request query params."},
                status=400,
            )

        # Teachers can only submit status updates for assigned section/subject.
        enforce_teacher_grade_access(request.user, section_id, subject_id)

        run_validation_checks(request)

        mp = MarkingPeriod.objects.only("id").filter(id=marking_period_id).first()
        if not mp:
            return Response(
                {
                    "detail": "This marking period does not exist or does not belong to the same academic year as the section."
                },
                status=404,
            )

        # Get workflow settings
        workflow_settings = get_workflow_settings()
        require_review = workflow_settings["require_grade_review"]
        require_approval = workflow_settings["require_grade_approval"]

        # Optimized query using denormalized fields to avoid JOINs
        grades = Grade.objects.select_for_update().filter(
            section_id=section_id,
            subject_id=subject_id,
            assessment__marking_period_id=marking_period_id,
        )

        # Apply targeted_status filter if provided
        if targeted_status is not None:
            t = targeted_status.split(",")
            grades = grades.filter(status__in=t)

        if not grades.exists():
            if targeted_status is not None:
                return Response(
                    {
                        "detail": f"No grades found for this section, subject, and marking period with status '{targeted_status}'."
                    },
                    status=404,
                )
            return Response(
                {
                    "detail": "No grades found for this section, subject, and marking period."
                },
                status=404,
            )

        updated_count = 0
        skipped_count = 0
        skip_reasons = {"approved": 0, "no_score": 0, "invalid_transition": 0}

        for grade in grades:
            if grade.status == Grade.Status.APPROVED:
                skipped_count += 1
                skip_reasons["approved"] += 1
                continue  # skip locked grades
            if grade.score is None:
                skipped_count += 1
                skip_reasons["no_score"] += 1
                continue  # skip grades without a score
            if not is_valid_transition(grade.status, target, require_review, require_approval):
                skipped_count += 1
                skip_reasons["invalid_transition"] += 1
                continue  # skip invalid transitions
            grade.status = target
            grade.updated_by = request.user
            grade.save(update_fields=["status", "updated_by", "updated_at"])
            updated_count += 1

        # Build detailed message
        message = f"Updated {updated_count} grade(s) to '{target}' status."
        if targeted_status is not None:
            message = f"Updated {updated_count} grade(s) from '{targeted_status}' to '{target}' status."
        if skipped_count > 0:
            skip_details = []
            if skip_reasons["approved"] > 0:
                skip_details.append(
                    f"{skip_reasons['approved']} already approved (locked)"
                )
            if skip_reasons["no_score"] > 0:
                skip_details.append(f"{skip_reasons['no_score']} without scores")
            if skip_reasons["invalid_transition"] > 0:
                skip_details.append(
                    f"{skip_reasons['invalid_transition']} invalid transitions"
                )
            message += f" Skipped {skipped_count}: {', '.join(skip_details)}."

        if updated_count == 0:
            raise ValidationError(
                {
                    "detail": "No grades were updated. All grades were either approved, had no score, or had invalid transitions."
                }
            )

        return Response(
            {
                "detail": message,
                "updated": updated_count,
                "skipped": skipped_count,
                "skip_reasons": skip_reasons,
            },
            status=200,
        )


class StudentMarkingPeriodGradeStatusTransitionView(APIView):
    permission_classes = [GradebookAccessPolicy]
    """
    PUT /students/<student_id>/marking-periods/<marking_period_id>/grades/status/
    { "status": "pending|reviewed|approved|draft", "targeted_status": "draft" (optional) }

    Changes the status of all grades for a specific student in a specific marking period.
    Requires subject_id as query parameter.
    """

    @transaction.atomic
    def put(self, request, student_id, marking_period_id):
        target = request.data.get("status")
        targeted_status = request.data.get("targeted_status")
        subject_id = request.query_params.get("subject")

        if target not in dict(Grade.Status.choices):
            return Response({"detail": f"Status '{target}' is invalid."}, status=400)

        if not subject_id:
            return Response(
                {"detail": "subject must be added to the request query params."},
                status=400,
            )

        run_validation_checks(request)

        # Get workflow settings
        workflow_settings = get_workflow_settings()
        require_review = workflow_settings["require_grade_review"]
        require_approval = workflow_settings["require_grade_approval"]

        # Verify student exists
        student = get_object_by_uuid_or_fields(Student, student_id, ["id_number", "prev_id_number"])

        # Verify marking period exists
        mp = get_object_or_404(
            MarkingPeriod.objects.only("id", "name"), pk=marking_period_id
        )

        # Get all grades for this student, marking period, and subject
        grades = Grade.objects.select_for_update().filter(
            student_id=student.id,
            subject_id=subject_id,
            assessment__marking_period_id=marking_period_id,
        )

        # Teachers can only transition grades in their assigned sections for this subject.
        allowed_section_ids = get_teacher_allowed_section_ids_for_subject(
            request.user,
            subject_id,
        )
        if allowed_section_ids is not None:
            grades = grades.filter(section_id__in=allowed_section_ids)

        # Apply targeted_status filter if provided
        if targeted_status is not None:
            grades = grades.filter(status=targeted_status)

        if not grades.exists():
            if targeted_status is not None:
                return Response(
                    {
                        "detail": f"No grades found for student {student.get_full_name()} in {mp.name} for the specified subject with status '{targeted_status}'."
                    },
                    status=404,
                )
            return Response(
                {
                    "detail": f"No grades found for student {student.get_full_name()} in {mp.name} for the specified subject."
                },
                status=404,
            )

        updated_count = 0
        skipped_count = 0
        skip_reasons = {"approved": 0, "no_score": 0, "invalid_transition": 0}

        for grade in grades:
            if grade.status == Grade.Status.APPROVED and target != Grade.Status.DRAFT:
                skipped_count += 1
                skip_reasons["approved"] += 1
                continue  # skip locked grades
            if grade.score is None:
                skipped_count += 1
                skip_reasons["no_score"] += 1
                continue  # skip grades without a score
            if not is_valid_transition(grade.status, target, require_review, require_approval):
                skipped_count += 1
                skip_reasons["invalid_transition"] += 1
                continue  # skip invalid transitions
            grade.status = target
            grade.updated_by = request.user
            grade.save(update_fields=["status", "updated_by", "updated_at"])
            updated_count += 1

        # Build detailed message
        message = f"Updated {updated_count} grade(s) to '{target}' status for {student.get_full_name()} in {mp.name}."
        if targeted_status is not None:
            message = f"Updated {updated_count} grade(s) from '{targeted_status}' to '{target}' status for {student.get_full_name()} in {mp.name}."
        if skipped_count > 0:
            skip_details = []
            if skip_reasons["approved"] > 0:
                skip_details.append(
                    f"{skip_reasons['approved']} already approved (locked)"
                )
            if skip_reasons["no_score"] > 0:
                skip_details.append(f"{skip_reasons['no_score']} without scores")
            if skip_reasons["invalid_transition"] > 0:
                skip_details.append(
                    f"{skip_reasons['invalid_transition']} invalid transitions"
                )
            message += f" Skipped {skipped_count}: {', '.join(skip_details)}."

        if updated_count == 0:
            raise ValidationError(
                {
                    "detail": "No grades were updated. All grades were either approved, had no score, or had invalid transitions."
                }
            )

        return Response(
            {
                "detail": message,
                "updated": updated_count,
                "skipped": skipped_count,
                "skip_reasons": skip_reasons,
            },
            status=200,
        )


class FinalGradeView(APIView):
    """
    POST /final-grade/   { "gradebook_id": "...", "student_id": "..." }
    """

    permission_classes = [GradebookAccessPolicy]

    def get(self, request):
        gb_id = request.query_params.get("gradebook_id")
        student_id = request.query_params.get("student_id")
        if not gb_id or not student_id:
            return Response(
                {"detail": "gradebook_id and student_id are required."}, status=400
            )

        gb = get_object_by_uuid_or_fields(GradeBook, gb_id)
        student = get_object_by_uuid_or_fields(Student.objects.only("id"), student_id)

        final_pct = gb.final_percentage_for_student(student)
        return Response(
            {
                "gradebook": str(gb.id),
                "student": str(student.id),
                "calculation_method": gb.calculation_method,
                "final_percentage": final_pct,
            },
            status=200,
        )


class GradeHistoryView(APIView):
    """
    Get change history for a specific grade.
    
    GET /api/v1/grading/grades/{grade_id}/history/
    """
    permission_classes = [GradebookAccessPolicy]

    def get(self, request, grade_id):
        from grading.models import GradeHistory
        
        try:
            grade = Grade.objects.get(id=grade_id)
        except Grade.DoesNotExist:
            from grading.response import GradingResponse
            return GradingResponse.error(
                message="Grade not found",
                error_code="GRADE_NOT_FOUND",
                status=404
            )
        
        history = GradeHistory.objects.filter(grade=grade).select_related(
            'changed_by'
        ).order_by('-created_at')
        
        history_data = [{
            "id": str(h.id),
            "change_type": h.change_type,
            "old_score": str(h.old_score) if h.old_score else None,
            "new_score": str(h.new_score) if h.new_score else None,
            "old_status": h.old_status,
            "new_status": h.new_status,
            "old_comment": h.old_comment,
            "new_comment": h.new_comment,
            "change_reason": h.change_reason,
            "changed_by": {
                "id": str(h.changed_by.id),
                "name": h.changed_by.get_full_name() or h.changed_by.username,
            } if h.changed_by else None,
            "changed_at": h.created_at.isoformat(),
        } for h in history]
        
        from grading.response import GradingResponse
        return GradingResponse.success(
            data=history_data,
            message=f"Retrieved {len(history_data)} history records"
        )


class GradeCorrectionView(APIView):
    """
    Correct/modify a grade at any time with optional reason.
    
    POST /api/v1/grading/grades/{grade_id}/correct/
    Body: {
        "score": 95.5,
        "comment": "Re-graded student work",
        "change_reason": "Grade correction - student appealed"
    }
    """
    permission_classes = [GradebookAccessPolicy]

    @transaction.atomic()
    def post(self, request, grade_id):
        from grading.response import GradingResponse
        
        try:
            grade = Grade.objects.get(id=grade_id)
        except Grade.DoesNotExist:
            return GradingResponse.error(
                message="Grade not found",
                error_code="GRADE_NOT_FOUND",
                status=404
            )
        
        # Extract correction data
        new_score = request.data.get('score')
        new_comment = request.data.get('comment')
        change_reason = request.data.get('change_reason', '')
        
        # Validate score if provided
        if new_score is not None:
            try:
                new_score = parse_decimal(new_score, "score")
                
                # Validate against assessment max_score
                if grade.assessment and new_score > grade.assessment.max_score:
                    return GradingResponse.validation_error(
                        message="Score exceeds assessment maximum",
                        field_errors={
                            "score": [f"Cannot exceed {grade.assessment.max_score}"]
                        }
                    )
                if new_score < 0:
                    return GradingResponse.validation_error(
                        message="Score cannot be negative",
                        field_errors={"score": ["Must be >= 0"]}
                    )
            except ValueError:
                return GradingResponse.validation_error(
                    message="Invalid score format",
                    field_errors={"score": ["Must be a valid number"]}
                )
        
        # Store old values for history
        old_score = grade.score
        old_comment = grade.comment
        
        # Apply changes
        if new_score is not None:
            grade.score = new_score
        
        if new_comment is not None:
            grade.comment = new_comment
        
        # Clear needs_correction flag since correction is being applied
        grade.needs_correction = False
        
        # Set updated_by for signal
        grade.updated_by = request.user
        
        # Save the grade (signals will auto-create history record)
        grade.save()
        
        # Create history with change reason
        from grading.models import GradeHistory
        GradeHistory.objects.create(
            grade=grade,
            old_score=old_score,
            new_score=grade.score,
            old_comment=old_comment,
            new_comment=grade.comment,
            changed_by=request.user,
            change_type="correction",
            change_reason=change_reason,
            ip_address=self.get_client_ip(request)
        )
        
        serializer = GradeOut(grade)
        return GradingResponse.success(
            data=serializer.data,
            message="Grade corrected successfully",
            correction={
                "old_score": str(old_score) if old_score else None,
                "new_score": str(grade.score) if grade.score else None,
                "reason": change_reason
            }
        )
    
    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class GradeMarkForCorrectionView(APIView):
    """
    Mark or unmark a grade for correction.
    
    POST /api/v1/grading/grades/{grade_id}/mark-for-correction/
    Body: {
        "needs_correction": true,
        "reason": "Optional reason for marking for correction"
    }
    """
    permission_classes = [GradebookAccessPolicy]

    def post(self, request, grade_id):
        from grading.response import GradingResponse
        
        try:
            grade = Grade.objects.get(id=grade_id)
        except Grade.DoesNotExist:
            return GradingResponse.error(
                message="Grade not found",
                error_code="GRADE_NOT_FOUND",
                status=404
            )
        
        needs_correction = request.data.get('needs_correction', True)
        reason = request.data.get('reason', '')
        
        # Update the flag
        grade.needs_correction = needs_correction
        grade.updated_by = request.user
        grade.save()
        
        # Optionally log this in history
        if needs_correction and reason:
            from grading.models import GradeHistory
            GradeHistory.objects.create(
                grade=grade,
                changed_by=request.user,
                change_type="correction",
                change_reason=f"Marked for correction: {reason}",
                ip_address=self.get_client_ip(request)
            )
        
        serializer = GradeOut(grade)
        return GradingResponse.success(
            data=serializer.data,
            message=f"Grade {'marked' if needs_correction else 'unmarked'} for correction"
        )
    
    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


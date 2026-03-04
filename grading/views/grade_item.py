
from django.db import transaction
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import GradebookAccessPolicy
from rest_framework.exceptions import NotFound
from django.db import IntegrityError

from common.utils import update_model_fields
from grading.utils import paginate_qs, parse_decimal

from grading.models import AssessmentType, Grade, GradeBook, Assessment
from grading.serializers import AssessmentOut

from academics.models import MarkingPeriod

class AssessmentsListCreateView(APIView):
    """
    GET  /assessments/?gradebook=&marking_period=&include_stats=
    POST /assessments/
    
    Query Parameters for GET:
    - marking_period: Required. Filter grade items by marking period
    - include_stats: Optional. Set to 'true' to include grade statistics for each grade item
    """
    def get_object(self, pk):
        try:
            f = Q(id=pk)
            return GradeBook.objects.select_related(
                "academic_year", 
                "section_subject", 
                "section_subject__section",
                "section_subject__subject"
                ).only(
                    "id", "active", "name", "calculation_method",
                    "section_subject", "academic_year",
                    "section_subject__section", "section_subject__subject"
                ).get(f)
        except GradeBook.DoesNotExist:
            raise NotFound("This gradebook does not exist.")

    def get(self, request, gradebook_id):
        marking_period_id = request.query_params.get("marking_period")

        if not marking_period_id:
            return Response({"detail": "marking_period query param is required."}, status=400)

        gradebook = self.get_object(gradebook_id)

        qs = gradebook.assessments.select_related(
            "gradebook", "assessment_type", "marking_period"
        ).only(
            "id", "active", "gradebook", "name", "assessment_type", "marking_period",
            "max_score", "weight", "due_date", "created_at", "updated_at"
        )

        if mp := marking_period_id:
            qs = qs.filter(marking_period_id=mp)
        
        # get the gradebook details
        gradebook_details = {
            "id": gradebook.id,
            "name": gradebook.name,
            "section": {
                "id": gradebook.section_subject.section.id,
                "name": gradebook.section_subject.section.name
            },
            "grade_level": {
                "id": gradebook.section_subject.section.grade_level.id,
                "name": gradebook.section_subject.section.grade_level.name
            }
        }

        page, meta = paginate_qs(qs, request)
        return Response({
            "meta": meta, 
            "results": AssessmentOut(page, many=True, context={'request': request}).data, 
            "gradebook": gradebook_details
        })

    def post(self, request, gradebook_id):
        name = request.data.get("name")
        assessment_type_id = request.data.get("assessment_type")
        mp1 = request.data.get("marking_period")
        mp2 = request.query_params.get("marking_period")
        marking_period_id = mp1 or mp2
        due_date = request.data.get("due_date")

        # Validate required fields
        if not name:
            return Response({"detail": "name is required."}, status=400)
        if not assessment_type_id:
            return Response({"detail": "assessment_type is required."}, status=400)
        if not marking_period_id:
            return Response({"detail": "marking_period is required."}, status=400)

        # Get gradebook with prefetched relationships
        gb = self.get_object(gradebook_id)
        
        # Validate related objects in a single query each
        try:
            # Batch validate assessment_type and marking_period
            assessment_type = AssessmentType.objects.only("id").get(id=assessment_type_id)
        except AssessmentType.DoesNotExist:
            return Response({"detail": "The assessment type does not exist."}, status=400)
        
        try:
            marking_period = MarkingPeriod.objects.only("id", "start_date", "end_date").get(id=marking_period_id)
        except MarkingPeriod.DoesNotExist:
            return Response({"detail": "The marking period does not exist."}, status=400)
        
        # Validate due date
        if due_date and not (marking_period.start_date <= due_date <= marking_period.end_date):
            return Response({"detail": f"Due date must be within the Marking Period {marking_period.start_date} - {marking_period.end_date}"}, status=400)
        
        # Check for duplicate grade item names (using exists() for efficiency)
        if Assessment.objects.filter(gradebook_id=gradebook_id, name__iexact=name).exists():
            return Response({"detail": "A grade item with this name already exists in this gradebook."}, status=400)

        # Parse numeric fields
        try:
            max_score = parse_decimal(request.data.get("max_score", 100), "max_score")
            weight = parse_decimal(request.data.get("weight", 1), "weight")
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        
        # Get section and subject from prefetched relationships
        section = gb.section_subject.section
        subject = gb.section_subject.subject
        
        try:
            with transaction.atomic():
                # Create the grade item
                obj = gb.assessments.create(
                    name=name,
                    assessment_type_id=assessment_type_id,
                    marking_period_id=marking_period_id,
                    max_score=max_score,
                    weight=weight,
                    due_date=due_date,
                    created_by=request.user, 
                    updated_by=request.user
                )
                
                # Optimized query for enrolled students - single query with select_related
                enrolled_students = section.enrollments.select_related('student').filter(
                    academic_year=gb.academic_year,  # Ensure correct academic year
                    status='active'
                ).only('student_id', 'student__id')  # Only fetch what we need
                
                # Create grade records efficiently
                if enrolled_students.exists():
                    grades = [
                        Grade(
                            assessment=obj,
                            student_id=enrollment.student_id,  # Use _id to avoid object loading
                            academic_year_id=gb.academic_year.id,
                            enrollment_id=enrollment.id,
                            section=section,
                            subject=subject,
                            score=None,
                            status=None,
                            created_by=request.user,
                            updated_by=request.user
                        )
                        for enrollment in enrolled_students
                    ]
                    
                    # Bulk create in batches for very large datasets
                    batch_size = 1000
                    for i in range(0, len(grades), batch_size):
                        Grade.objects.bulk_create(grades[i:i + batch_size])
                        
        except IntegrityError as e:
            return Response({"detail": "Database integrity error. " + str(e)}, status=400)
        except Exception as e:
            return Response({"detail": "Failed to create grade item. " + str(e)}, status=400)
            
        return Response(AssessmentOut(obj, context={'request': request}).data, status=201)

class AssessmentsDetailView(APIView):
    def get_object(self, pk):
        try:
            return Assessment.objects.select_related("gradebook", "assessment_type", "marking_period").get(pk=pk)
        except Assessment.DoesNotExist:
            raise NotFound("This grade item does not exist.")

    def get(self, request, pk):
        item = self.get_object(pk)
        return Response(AssessmentOut(item, context={'request': request}).data)

    def put(self, request, pk):
        item = self.get_object(pk)

        allowed_fields = ["name", "assessment_type_id", "marking_period_id", "max_score", "weight", "due_date"]

        return update_model_fields(request, item, allowed_fields, AssessmentOut)

    @transaction.atomic
    def delete(self, request, pk):
        item = self.get_object(pk)
        item.delete()
        return Response(status=204)


from django.db import transaction
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import GradebookAccessPolicy
from rest_framework.exceptions import NotFound

from common.utils import update_model_fields
from grading.utils import paginate_qs, generate_assessments_for_gradebook_with_settings

from grading.models import GradeBook
from grading.serializers import GradeBookOut

from academics.models import AcademicYear, SectionSubject

class GradeBookListCreateView(APIView):
    permission_classes = [GradebookAccessPolicy]
    """
    GET  /gradebooks/?section_subject=&academic_year=&include_stats=true
    POST /gradebooks/ {section_subject, academic_year, name, calculation_method, auto_generate_assessments}
    
    Query Parameters:
    - section_subject: Filter by section subject ID
    - section: Filter by section ID  
    - include_stats: Include statistics (true/false) - adds grade item counts and overall average
    
    POST Body Parameters:
    - auto_generate_assessments: Auto-generate assessments based on settings (default: true)
    """
    def get_object(self, pk):
        try:
            return AcademicYear.objects.only("id").get(pk=pk)
        except AcademicYear.DoesNotExist:
            raise NotFound("This academic year does not exist.")

    def get(self, request, academic_year_id):
        academic_year: AcademicYear = self.get_object(academic_year_id)

        qs = academic_year.gradebooks.select_related(
            "section_subject",
            "section_subject__section", "section_subject__subject"
        ).only(
            "id", "active", "name", "calculation_method",
            "section_subject", "academic_year", "created_at", "updated_at",
            "section_subject__section__name", "section_subject__subject__name",
            "academic_year__name",
        )

        if ss := request.query_params.get("section_subject"):
            qs = qs.filter(section_subject_id=ss)
        
        if sct := request.query_params.get("section"):
            qs = qs.filter(section_id=sct)
        # if ay := request.query_params.get("academic_year"):
        #     qs = qs.filter(academic_year_id=ay)

        # Check if stats should be included
        include_stats = request.query_params.get("include_stats", "").lower() in ("true", "1", "yes")

        page, meta = paginate_qs(qs, request)
        return Response({
            "meta": meta, 
            "results": GradeBookOut(page, many=True, include_stats=include_stats).data
        })

    @transaction.atomic
    def post(self, request, academic_year_id):
        
        method = request.data.get("calculation_method", GradeBook.CalculationMethod.AVERAGE)
        name = (request.data.get("name") or "").strip()
        section_subject_id = request.data.get("section_subject")
        auto_generate = request.data.get("auto_generate_assessments", True)
        
        # Convert string booleans to actual booleans
        if isinstance(auto_generate, str):
            auto_generate = auto_generate.lower() in ("true", "1", "yes")
        
        if not section_subject_id:
            return Response({"detail": "section_subject is required."}, status=400)
        
        if not name:
            return Response({"detail": "name is required."}, status=400)
        
        academic_year = self.get_object(academic_year_id)
        section_subject = SectionSubject.objects.select_related("section", "subject").filter(id=section_subject_id).first()
        if not section_subject:
            return Response({"detail": "The section subject does not exist."}, status=400)
        
        if method not in dict(GradeBook.CalculationMethod.choices):
            return Response({"detail": "Invalid calculation_method."}, status=400)

        obj = academic_year.gradebooks.create(
            section_subject_id=section_subject_id,
            name=name,
            calculation_method=method,
            created_by=request.user, 
            updated_by=request.user
        )
        
        # Auto-generate assessments if requested
        generation_result = None
        if auto_generate:
            generation_result = generate_assessments_for_gradebook_with_settings(
                obj,
                created_by=request.user
            )
        
        # Check if stats should be included in response
        include_stats = request.query_params.get("include_stats", "").lower() in ("true", "1", "yes")
        
        response_data = GradeBookOut(obj, include_stats=include_stats).data
        if generation_result:
            response_data['assessment_generation'] = generation_result
        
        return Response(response_data, status=201)

class GradeBookDetailView(APIView):    
    permission_classes = [GradebookAccessPolicy]
    def get_object(self, pk):
        try:
            f = Q(pk=pk)
            return GradeBook.objects.select_related(
                "section_subject", "academic_year",
                "section_subject__section", "section_subject__subject"
            ).get(f)
        except GradeBook.DoesNotExist:
            raise NotFound("This grade book does not exist.")

    def get(self, request, pk):
        gb = self.get_object(pk)
        # Check if stats should be included
        include_stats = request.query_params.get("include_stats", "").lower() in ("true", "1", "yes")
        return Response(GradeBookOut(gb, include_stats=include_stats).data)

    @transaction.atomic
    def put(self, request, pk):
        gb = self.get_object(pk)
        
        allowed_fields = ["name", "calculation_method"]

        # Check if stats should be included in response
        include_stats = request.query_params.get("include_stats", "").lower() in ("true", "1", "yes")
        
        serializer = update_model_fields(request, gb, allowed_fields, 
                                       lambda obj: GradeBookOut(obj, include_stats=include_stats))
        return Response(serializer.data)

    @transaction.atomic
    def delete(self, request, pk):
        gb = self.get_object(pk)
        # if gb.assessments.exists():
        #     gb.active = False
        #     gb.save(update_fields=["active", "updated_at"])
        #     return Response({"detail": "Cannot delete grade book with associated grade items."}, status=409)
        gb.delete()
        return Response(status=204)

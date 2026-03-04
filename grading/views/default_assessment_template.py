from django.db import transaction
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import GradebookAccessPolicy
from rest_framework.exceptions import NotFound, ValidationError

from common.utils import update_model_fields
from grading.utils import (
    paginate_qs,
    generate_default_assessments_for_gradebook,
    generate_default_assessments_for_academic_year,
    preview_default_assessments_for_gradebook,
    generate_assessments_for_gradebook_with_settings
)

from grading.models import DefaultAssessmentTemplate, GradeBook
from grading.serializers import (
    DefaultAssessmentTemplateOut,
    DefaultAssessmentTemplateIn,
    AssessmentGenerationPreviewOut,
    BulkAssessmentGenerationResultOut
)

from academics.models import AcademicYear

class DefaultAssessmentTemplateListCreateView(APIView):
    """
    GET: List all default assessment templates for a school
    POST: Create a new default assessment template
    """

    def get(self, request, school_id=None):
        """List all templates"""
        
        # Optional filters
        is_active = request.query_params.get('is_active')
        assessment_type_id = request.query_params.get('assessment_type')
        
        qs = DefaultAssessmentTemplate.objects.select_related(
            'assessment_type',
        ).order_by('order', 'name')
        
        # Apply filters
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == 'true')
        
        if assessment_type_id:
            qs = qs.filter(assessment_type_id=assessment_type_id)
        
        return Response(DefaultAssessmentTemplateOut(qs, many=True).data)

    @transaction.atomic
    def post(self, request, school_id=None):
        """Create a new template"""
        
        # Extract data from request
        name = request.data.get('name')
        assessment_type_id = request.data.get('assessment_type')
        max_score = request.data.get('max_score', 100)
        weight = request.data.get('weight', 1)
        is_calculated = request.data.get('is_calculated', True)
        order = request.data.get('order', 0)
        description = request.data.get('description', '').strip()
        is_active = request.data.get('is_active', True)
        
        # Validate required fields
        if not name:
            return Response({"detail": "name is required."}, status=400)
        
        if not assessment_type_id:
            return Response({"detail": "assessment_type is required."}, status=400)
        
        # Validate max_score and weight
        try:
            max_score = float(max_score)
            if max_score <= 0:
                return Response({"detail": "max_score must be greater than 0."}, status=400)
        except (ValueError, TypeError):
            return Response({"detail": "max_score must be a valid number."}, status=400)
        
        try:
            weight = float(weight)
            if weight <= 0:
                return Response({"detail": "weight must be greater than 0."}, status=400)
        except (ValueError, TypeError):
            return Response({"detail": "weight must be a valid number."}, status=400)
        
        # Verify assessment_type exists and belongs to same school
        try:
            from grading.models import AssessmentType
            assessment_type = AssessmentType.objects.get(pk=assessment_type_id)
        except AssessmentType.DoesNotExist:
            return Response({"detail": "Assessment type not found."}, status=404)
        
        # Create template
        template = DefaultAssessmentTemplate.objects.create(
            name=name,
            assessment_type=assessment_type,
            max_score=max_score,
            weight=weight,
            is_calculated=is_calculated,
            order=order,
            description=description or None,
            is_active=is_active,
            created_by=request.user,
            updated_by=request.user
        )
        
        return Response(
            DefaultAssessmentTemplateOut(template).data,
            status=201
        )

class DefaultAssessmentTemplateDetailView(APIView):
    permission_classes = [GradebookAccessPolicy]
    """
    GET: Retrieve a specific template
    PATCH: Update a template
    DELETE: Delete a template (or deactivate if in use)
    """
    
    def get_object(self, pk):
        try:
            return DefaultAssessmentTemplate.objects.select_related(
                'assessment_type'
            ).get(pk=pk)
        except DefaultAssessmentTemplate.DoesNotExist:
            raise NotFound("This template does not exist.")
    
    def get(self, request, pk):
        """Retrieve template details"""
        obj = self.get_object(pk)
        return Response(DefaultAssessmentTemplateOut(obj).data)

    @transaction.atomic
    def patch(self, request, pk):
        """Update template"""
        obj = self.get_object(pk)
        
        allowed_fields = [
            'name', 'assessment_type', 'max_score', 'weight',
            'is_calculated', 'order', 'description', 'is_active'
        ]
        
        serializer = update_model_fields(
            request, obj, allowed_fields, DefaultAssessmentTemplateOut
        )
        return Response(serializer.data)

    @transaction.atomic
    def delete(self, request, pk):
        """Delete template"""
        obj = self.get_object(pk)
        obj.delete()
        return Response(status=204)

class GenerateAssessmentsForGradebookView(APIView):
    """
    Generate assessments for a gradebook based on school settings.
    
    POST /api/v1/grading/gradebooks/{gradebook_id}/generate-assessments/
    """
    
    def get_gradebook(self, gradebook_id):
        try:
            return GradeBook.objects.select_related(
                'section_subject__section__school',
                'academic_year'
            ).get(pk=gradebook_id)
        except GradeBook.DoesNotExist:
            raise NotFound("This gradebook does not exist.")
    
    @transaction.atomic
    def post(self, request, gradebook_id):
        """
        Generate assessments for a gradebook.
        
        Respects school grading settings:
        - Single Entry: Creates one "Final Grade" per marking period
        - Multiple Entry: Uses assessment templates
        """
        gradebook = self.get_gradebook(gradebook_id)
        
        # Check if dry_run mode
        dry_run = request.data.get('dry_run', False)
        
        if dry_run:
            # Preview mode - don't create
            preview = preview_default_assessments_for_gradebook(gradebook)
            return Response(
                AssessmentGenerationPreviewOut(preview).data,
                status=200
            )
        
        # Generate assessments based on settings
        result = generate_assessments_for_gradebook_with_settings(
            gradebook,
            created_by=request.user
        )
        
        return Response({
            'success': True,
            'gradebook_id': str(gradebook.id),
            'gradebook_name': gradebook.name,
            'mode': result['mode'],
            'assessments_created': result['assessments_created'],
            'assessment_ids': result['assessment_ids'],
            'message': result['message']
        }, status=201)

class GenerateAssessmentsForAcademicYearView(APIView):
    """
    POST: Generate default assessments for all gradebooks in an academic year
    """
    
    def get_academic_year(self, academic_year_id):
        try:
            return AcademicYear.objects.get(pk=academic_year_id)
        except AcademicYear.DoesNotExist:
            raise NotFound("This academic year does not exist.")
    
    @transaction.atomic
    def post(self, request, academic_year_id):
        """
        Bulk generate assessments for all gradebooks in academic year.
        
        Query Parameters:
        - school_id: Optional school filter
        - regenerate: If true, delete all existing assessments and regenerate
        - override_existing: If true, allow regeneration even if grades exist (DANGEROUS!)
        """
        academic_year = self.get_academic_year(academic_year_id)
        
        # Check for regenerate mode
        regenerate = request.data.get('regenerate', False)
        override_existing = request.data.get('override_existing', False)
        
        if regenerate:
            # REGENERATE MODE: Delete and recreate
            from grading.utils import regenerate_assessments_for_academic_year
            
            try:
                result = regenerate_assessments_for_academic_year(
                    academic_year,
                    created_by=request.user,
                    override_existing=override_existing
                )
                
                return Response({
                    'success': True,
                    'mode': 'regenerate',
                    'templates_found': result['templates_found'],
                    'gradebooks_processed': result['gradebooks_processed'],
                    'assessments_deleted': result['assessments_deleted'],
                    'assessments_created': result['assessments_created'],
                    'grades_affected': result['grades_affected'],
                    'gradebooks_with_errors': result['gradebooks_with_errors'],
                    'error_count': len(result['gradebooks_with_errors'])
                }, status=201)
                
            except ValueError as e:
                return Response(
                    {"detail": str(e)},
                    status=400
                )
        else:
            # NORMAL MODE: Only create new assessments
            result = generate_default_assessments_for_academic_year(
                academic_year,
                created_by=request.user
            )
            
            return Response(
                BulkAssessmentGenerationResultOut(result).data,
                status=201
            )

class PreviewAssessmentsForGradebookView(APIView):
    """
    GET: Preview what assessments would be generated for a gradebook
    """
    
    def get_gradebook(self, gradebook_id):
        try:
            return GradeBook.objects.select_related(
                'section_subject__section__school',
                'academic_year'
            ).get(pk=gradebook_id)
        except GradeBook.DoesNotExist:
            raise NotFound("This gradebook does not exist.")
    
    def get(self, request, gradebook_id):
        """Preview assessment generation"""
        gradebook = self.get_gradebook(gradebook_id)
        
        preview = preview_default_assessments_for_gradebook(gradebook)
        
        return Response(
            AssessmentGenerationPreviewOut(preview).data,
            status=200
        )

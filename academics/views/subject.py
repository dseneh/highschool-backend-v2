from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy

from common.utils import create_model_data, update_model_fields
from common.cache_service import DataCache

from ..models import Subject
from ..serializers import SubjectSerializer

# Business logic imports
from business.core.services import subject_service
from business.core.adapters import subject_adapter

class SubjectListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    def get(self, request):
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        subjects = DataCache.get_subjects(force_refresh)
        
        return Response(subjects, status=status.HTTP_200_OK)

    def post(self, request):
        req_data: dict = request.data

        # Validate using business logic
        validation_result = subject_service.validate_subject_creation(
            name=req_data.get("name"),
            code=req_data.get("code"),
            credits=req_data.get("credits")
        )
        
        if not validation_result["valid"]:
            return Response({"detail": validation_result["error"]}, status=400)
        
        # Check for duplicates
        if Subject.objects.filter(name__iexact=validation_result["data"]["name"]).exists():
            return Response(
                {"detail": f"Subject already exists with '{validation_result['data']['name']}'"}, status=400
            )
        
        data = {
            "name": validation_result["data"]["name"],
            "code": validation_result["data"].get("code"),
            "description": validation_result["data"].get("description"),
            "credits": validation_result["data"].get("credits"),
        }
        
        try:
            subject = subject_adapter.create_subject_in_db(
                data=data,
                user=request.user
            )
            serializer = SubjectSerializer(subject, context={"request": request})
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

class SubjectDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        try:
            return Subject.objects.get(id=id)
        except Subject.DoesNotExist:
            raise NotFound("Subject does not exist with this id")

    def get(self, request, id):
        subject = self.get_object(id)
        serializer = SubjectSerializer(subject, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        subject = self.get_object(id)

        allowed_fields = [
            "name",
            "description",
            "active",
        ]

        serializer = update_model_fields(
            request, subject, allowed_fields, SubjectSerializer
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        try:
            subject = self.get_object(id)
            force = request.query_params.get('force', 'false').lower() == 'true'

            # Check if any grades/gradebooks exist for this subject
            from grading.models import Grade, GradeBook
            
            # Check if grades with scores exist
            has_scored_grades = Grade.objects.filter(subject=subject, score__isnull=False).exists()
            has_gradebooks = GradeBook.objects.filter(subject=subject).exists()
            has_grade_records = Grade.objects.filter(subject=subject).exists()
            has_grades = has_gradebooks or has_grade_records
            
            if has_scored_grades:
                # Grades with scores exist - can only deactivate, never delete
                subject.active = False
                subject.save()
                return Response(
                    {
                        "detail": "Subject has grades with scores and has been deactivated. It cannot be deleted."
                    },
                    status=200,
                )
            
            # No scored grades - check if safe to delete
            if has_grades or subject.section_subjects.exists():
                # Has unscored grades/gradebooks or related records
                if force:
                    # Force delete - remove all related records
                    grades_count = Grade.objects.filter(subject=subject).count()
                    gradebooks_count = GradeBook.objects.filter(subject=subject).count()
                    section_subjects_count = subject.section_subjects.count()
                    
                    # Delete in order
                    Grade.objects.filter(subject=subject).delete()
                    GradeBook.objects.filter(subject=subject).delete()
                    subject.section_subjects.all().delete()
                    subject.delete()
                    
                    return Response(
                        {
                            "detail": f"Subject deleted along with {gradebooks_count} gradebook(s), {grades_count} grade record(s), and {section_subjects_count} section assignment(s)."
                        },
                        status=status.HTTP_200_OK,
                    )
                else:
                    # No force - deactivate instead
                    subject.active = False
                    subject.save()
                    return Response(
                        {
                            "detail": "Subject has associated records and has been deactivated. Pass 'force=true' to delete permanently."
                        },
                        status=status.HTTP_200_OK,
                    )
            
            # No related records at all - safe to delete directly
            subject.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        except Exception as e:
            return Response(
                {"detail": f"Error deleting subject: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

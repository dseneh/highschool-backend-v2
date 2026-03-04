
from django.db import transaction
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import GradebookAccessPolicy
from rest_framework.exceptions import NotFound

from common.utils import update_model_fields
from grading.utils import paginate_qs

from grading.models import AssessmentType
from grading.serializers import AssessmentTypeOut

class AssessmentTypeListCreateView(APIView):

    def get(self, request):
        qs = AssessmentType.objects.only(
            "id", "active", "name", "description", "created_at", "updated_at"
        )
        # page, meta = paginate_qs(qs, request)
        return Response(AssessmentTypeOut(qs, many=True).data)

    @transaction.atomic
    def post(self, request):
        
        name = request.data.get("name")
        description = (request.data.get("description") or "").strip()

        if not name:
            return Response({"detail": "name is required."}, status=400)

        obj = AssessmentType.objects.create(
            name=name,
            description=description,
            created_by=request.user, 
            updated_by=request.user
        )
        return Response(AssessmentTypeOut(obj).data, status=201)

class AssessmentTypeDetailView(APIView):
    permission_classes = [GradebookAccessPolicy]
    # permission_classes = [permissions.IsAuthenticated]
    def get_object(self, pk):
        try:
            return AssessmentType.objects.get(pk=pk)
        except AssessmentType.DoesNotExist:
            raise NotFound("This assessment type does not exist.")
    
    def get(self, request, pk):
        obj = self.get_object(pk)
        return Response(AssessmentTypeOut(obj).data)

    @transaction.atomic
    def patch(self, request, pk):
        obj = self.get_object(pk)

        allowed_fields = ["name", "description", "active"]

        serializer = update_model_fields(request, obj, allowed_fields, AssessmentTypeOut)
        return Response(serializer.data)

    @transaction.atomic
    def delete(self, request, pk):
        obj = self.get_object(pk)
        
        # see if any Assessmentss exist with this type
        if obj.assessments.exists():
            obj.active = False
            obj.save(update_fields=["active", "updated_at"])
            return Response({"detail": "Cannot delete assessment type with associated grade items."}, status=409)
        
        obj.delete()
        return Response(status=204)


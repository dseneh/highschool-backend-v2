from django.db import transaction
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import GradebookAccessPolicy
from rest_framework.exceptions import NotFound

from common.utils import update_model_fields
from grading.utils import paginate_qs

from grading.models import GradeLetter
from grading.serializers import GradeLetterOut

class GradeLetterListCreateView(APIView):

    def get(self, request, school_id):
        qs = GradeLetter.objects.only(
            "id", "active", "letter", "min_percentage", "max_percentage", 
            "order", "created_at", "updated_at"
        ).order_by('order', '-max_percentage')
        
        page, meta = paginate_qs(qs, request)
        return Response({"meta": meta, "results": GradeLetterOut(page, many=True).data})

    @transaction.atomic
    def post(self, request):
        letter = request.data.get("letter")
        min_percentage = request.data.get("min_percentage")
        max_percentage = request.data.get("max_percentage")
        order = request.data.get("order", 0)

        if not letter:
            return Response({"detail": "letter is required."}, status=400)
        if min_percentage is None:
            return Response({"detail": "min_percentage is required."}, status=400)
        if max_percentage is None:
            return Response({"detail": "max_percentage is required."}, status=400)

        try:
            obj = GradeLetter.objects.create(
                letter=letter,
                min_percentage=min_percentage,
                max_percentage=max_percentage,
                order=order,
                created_by=request.user, 
                updated_by=request.user
            )

            return Response(GradeLetterOut(obj).data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

class GradeLetterDetailView(APIView):
    permission_classes = [GradebookAccessPolicy]
    
    def get_object(self, pk):
        try:
            return GradeLetter.objects.get(pk=pk)
        except GradeLetter.DoesNotExist:
            raise NotFound("This grade letter does not exist.")
    
    def get(self, request, pk):
        obj = self.get_object(pk)
        return Response(GradeLetterOut(obj).data)

    @transaction.atomic
    def patch(self, request, pk):
        obj = self.get_object(pk)

        allowed_fields = ["letter", "min_percentage", "max_percentage", "order", "active"]

        serializer = update_model_fields(request, obj, allowed_fields, GradeLetterOut)
        return Response(serializer.data)

    @transaction.atomic
    def delete(self, request, pk):
        obj = self.get_object(pk)
        
        # Check if this is the only grade letter
        if GradeLetter.objects.count() <= 1:
            return Response({"detail": "Cannot delete the last grade letter."}, status=409)
        
        obj.delete()
        return Response(status=204)
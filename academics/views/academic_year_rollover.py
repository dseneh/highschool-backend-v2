from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.access_policies import AcademicsAccessPolicy
from academics.services.academic_year_rollover import apply_rollover, preview_rollover


class AcademicYearRolloverPreviewView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def post(self, request):
        try:
            result = preview_rollover(dict(request.data))
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class AcademicYearRolloverApplyView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def post(self, request):
        try:
            result = apply_rollover(dict(request.data), actor=request.user)
            return Response(result, status=status.HTTP_201_CREATED)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

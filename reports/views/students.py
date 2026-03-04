"""
Student Reports Views

Placeholder for future student reporting functionality including:
- Student performance reports
- Enrollment reports
- Student billing summaries
"""

from rest_framework.views import APIView
from ..access_policies import ReportsAccessPolicy
from rest_framework.response import Response
from rest_framework import status

class StudentReportView(APIView):
    permission_classes = [ReportsAccessPolicy]
    """
    View to generate student reports
    TODO: Implement student reporting functionality
    """

    def get(self, request, school_id):
        return Response({
            'message': 'Student reports not yet implemented',
            'school_id': school_id,
            'available_soon': True
        }, status=status.HTTP_501_NOT_IMPLEMENTED)

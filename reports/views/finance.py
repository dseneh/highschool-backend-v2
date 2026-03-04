"""
Finance Reports Views

Placeholder for future finance reporting functionality including:
- Financial summaries
- Revenue reports
- Payment analysis
"""

from rest_framework.views import APIView
from ..access_policies import ReportsAccessPolicy
from rest_framework.response import Response
from rest_framework import status

class FinanceReportView(APIView):
    permission_classes = [ReportsAccessPolicy]
    """
    View to generate finance reports
    TODO: Implement finance reporting functionality
    """

    def get(self, request, school_id):
        return Response({
            'message': 'Finance reports not yet implemented',
            'school_id': school_id,
            'available_soon': True
        }, status=status.HTTP_501_NOT_IMPLEMENTED)

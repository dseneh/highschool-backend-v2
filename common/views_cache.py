"""
API views for accessing cached reference data.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from common.cache_service import DataCache
import logging

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_reference_data(request):
    """
    Get all cached reference data for a tenant.
    
    Query Parameters:
        - academic_year_id: Filter sections, semesters, installments by academic year
        - force_refresh: If 'true', bypass cache and fetch fresh data
        - include_hidden: If 'true', include hidden transaction types
    
    Returns:
        Dictionary containing all reference data:
        - grade_levels
        - sections
        - academic_years
        - current_academic_year
        - semesters
        - marking_periods (if semester_id provided)
        - subjects
        - payment_methods
        - transaction_types
        - installments
    """
    try:
        # Get query parameters
        academic_year_id = request.query_params.get('academic_year_id')
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        include_hidden = request.query_params.get('include_hidden', 'false').lower() == 'true'
        
        # Get all reference data
        data = {
            'divisions': DataCache.get_divisions(force_refresh, request=request),
            'grade_levels': DataCache.get_grade_levels(force_refresh, request=request),
            'sections': DataCache.get_sections(academic_year_id, force_refresh, request=request),
            'academic_years': DataCache.get_academic_years(force_refresh, request=request),
            'current_academic_year': DataCache.get_current_academic_year(force_refresh, request=request),
            'semesters': DataCache.get_semesters(academic_year_id, force_refresh, request=request),
            'marking_periods': DataCache.get_marking_periods(academic_year_id, None, force_refresh, request=request),
            'subjects': DataCache.get_subjects(force_refresh, request=request),
            'payment_methods': DataCache.get_payment_methods(force_refresh, request=request),
            'transaction_types': DataCache.get_transaction_types(include_hidden, force_refresh, request=request),
            'installments': DataCache.get_installments(academic_year_id, force_refresh, request=request),
        }
        
        return Response(data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error fetching reference data for tenant scope: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch reference data', 'detail': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_sections(request):
    """Get sections for a tenant, optionally filtered by academic year."""
    try:
        academic_year_id = request.query_params.get('academic_year_id')
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        data = DataCache.get_sections(academic_year_id, force_refresh, request=request)
        return Response(data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching sections: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_divisions(request):
    """Get all divisions for a tenant."""
    try:
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        data = DataCache.get_divisions(force_refresh, request=request)
        return Response(data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching divisions: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_grade_levels(request):
    """Get all grade levels for a tenant."""
    try:
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        data = DataCache.get_grade_levels(force_refresh, request=request)
        return Response(data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching grade levels: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_academic_years(request):
    """Get all academic years for a tenant."""
    try:
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        data = DataCache.get_academic_years(force_refresh, request=request)
        return Response(data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching academic years: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_current_academic_year(request):
    """Get the current academic year for a tenant."""
    try:
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        data = DataCache.get_current_academic_year(force_refresh, request=request)
        if data is None:
            return Response(
                {'error': 'No current academic year found'},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response(data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error fetching current academic year: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def invalidate_cache(request):
    """
    Manually invalidate cache for specific data types or all data.
    
    Body:
        {
            "data_type": "all" | "grade_levels" | "sections" | "academic_years" | 
                        "semesters" | "marking_periods" | "subjects" | 
                        "payment_methods" | "transaction_types" | "installments"
        }
    """
    try:
        data_type = request.data.get('data_type', 'all')
        
        if data_type == 'all':
            DataCache.invalidate_all(request=request)
            message = "Invalidated all cache for tenant scope"
        elif data_type == 'grade_levels':
            DataCache.invalidate_grade_levels(request=request)
            message = "Invalidated grade levels cache"
        elif data_type == 'sections':
            DataCache.invalidate_sections(request=request)
            message = "Invalidated sections cache"
        elif data_type == 'academic_years':
            DataCache.invalidate_academic_years(request=request)
            message = "Invalidated academic years cache"
        elif data_type == 'semesters':
            DataCache.invalidate_semesters(request=request)
            message = "Invalidated semesters cache"
        elif data_type == 'marking_periods':
            DataCache.invalidate_marking_periods(request=request)
            message = "Invalidated marking periods cache"
        elif data_type == 'subjects':
            DataCache.invalidate_subjects(request=request)
            message = "Invalidated subjects cache"
        elif data_type == 'payment_methods':
            DataCache.invalidate_payment_methods(request=request)
            message = "Invalidated payment methods cache"
        elif data_type == 'transaction_types':
            DataCache.invalidate_transaction_types(request=request)
            message = "Invalidated transaction types cache"
        elif data_type == 'installments':
            DataCache.invalidate_installments(request=request)
            message = "Invalidated installments cache"
        else:
            return Response(
                {'error': f'Invalid data_type: {data_type}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response({'message': message}, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error invalidating cache: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

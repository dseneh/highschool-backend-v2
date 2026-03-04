"""
Cache service for frequently accessed reference data that rarely changes.

This service provides caching for:
- Grade levels
- Sections
- Academic years (including current)
- Semesters
- Marking periods
- Subjects
- Payment methods
- Transaction types
- Installments

Cache is invalidated automatically via signals when data changes.
Cache is tenant-aware (per tenant).
"""
from typing import Optional, List, Dict, Any
from django.db import connection
from django.core.cache import cache
from django.db.models import QuerySet, Q
import logging

from business.core.adapters.supporting_adapter import section_subject_has_grades
from common.utils import get_tenant_from_request

logger = logging.getLogger(__name__)

# Cache key prefixes for organization
CACHE_PREFIX = "ref_data"

# Cache timeout: 24 hours (data rarely changes)
# Can be overridden in settings with REFERENCE_DATA_CACHE_TIMEOUT
DEFAULT_CACHE_TIMEOUT = 86400  # 24 hours


class DataCache:
    """
    Service class for caching reference/lookup data that doesn't change frequently.
    All methods are tenant-aware and cache data per tenant.
    """

    @staticmethod
    def _resolve_scope(request=None) -> str:
        """Resolve cache scope using tenant header, schema name, or provided id."""
        tenant_header = get_tenant_from_request(request)
        schema_name = getattr(connection, "schema_name", None)
        return tenant_header or schema_name

    @staticmethod
    def _get_cache_key(data_type: str, suffix: str = "", request=None) -> str:
        """Generate consistent cache key format."""
        scope = DataCache._resolve_scope(request)
        key = f"{CACHE_PREFIX}:{scope}:{data_type}"
        if suffix:
            key = f"{key}:{suffix}"
        return key

    @staticmethod
    def _get_timeout() -> int:
        """Get cache timeout from settings or use default."""
        from django.conf import settings
        return getattr(settings, 'REFERENCE_DATA_CACHE_TIMEOUT', DEFAULT_CACHE_TIMEOUT)

    @staticmethod
    def _get_cached_data(
        data_type: str,
        query_func,
        suffix: str = "",
        force_refresh: bool = False,
        request=None,
    ) -> List[Dict[str, Any]]:
        """
        Generic method to get cached data or fetch from database.
        
        Args:
            data_type: Type of data (for cache key)
            query_func: Callable that returns the data from database
            suffix: Optional cache key suffix
            force_refresh: If True, bypass cache
            
        Returns:
            List of data dictionaries
        """
        cache_key = DataCache._get_cache_key(data_type, suffix, request)
        
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache HIT: {data_type} for scope {cache_key}")
                return cached
        
            logger.debug(f"Cache MISS: {data_type} for scope {cache_key}")
        
        # Fetch data from database
        data = query_func()
        
        # Cache the result
        cache.set(cache_key, data, DataCache._get_timeout())
        return data

    @staticmethod
    def _invalidate_cache(data_type: str, *suffixes: str, request=None):
        """
        Generic method to invalidate cache.
        
        Args:
            data_type: Type of data (for cache key)
            *suffixes: Optional suffixes for multiple cache keys
        """
        if suffixes:
            for suffix in suffixes:
                cache_key = DataCache._get_cache_key(data_type, suffix, request)
                cache.delete(cache_key)
        else:
            cache_key = DataCache._get_cache_key(data_type, request=request)
            cache.delete(cache_key)
        scope = DataCache._resolve_scope(request)
        logger.debug(f"Invalidated cache: {data_type} for scope {scope}")

    # ==================== DIVISIONS ====================
    
    @staticmethod
    def get_divisions(force_refresh: bool = False, request=None) -> List[Dict[str, Any]]:
        """Get all divisions for a tenant from cache or database."""
        from academics.models import Division
        
        def query():
            return list(
                Division.objects.all()
                .order_by('name')
                .values('id', 'name', 'description')
            )
        
        return DataCache._get_cached_data("divisions", query, force_refresh=force_refresh, request=request)

    @staticmethod
    def invalidate_divisions(request=None):
        """Invalidate divisions cache for a tenant."""
        DataCache._invalidate_cache("divisions", request=request)

    # ==================== GRADE LEVELS ====================
    
    @staticmethod
    def get_grade_levels(force_refresh: bool = False, request=None) -> List[Dict[str, Any]]:
        """Get all grade levels for a tenant from cache or database."""
        from academics.models import GradeLevel
        
        def query():
            return list(
                GradeLevel.objects.filter(active=True)
                .order_by('level', 'name')
                .values('id', 'name', 'short_name', 'level')
            )
        
        return DataCache._get_cached_data("grade_levels", query, force_refresh=force_refresh, request=request)

    @staticmethod
    def invalidate_grade_levels(request=None):
        """Invalidate grade levels cache for a tenant."""
        DataCache._invalidate_cache("grade_levels", request=request)

    # ==================== SECTIONS ====================
    
    @staticmethod
    def get_sections(
        academic_year_id: Optional[str] = None,
        force_refresh: bool = False,
        request=None,
    ) -> List[Dict[str, Any]]:
        """Get sections for a tenant, optionally filtered by academic year."""
        suffix = f"ay_{academic_year_id}" if academic_year_id else "all"
        cache_key = DataCache._get_cache_key("sections", suffix, request)

        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache HIT: sections for scope {cache_key}, ay={academic_year_id}")
                return cached

            logger.debug(f"Cache MISS: sections for scope {cache_key}, ay={academic_year_id}")

        from academics.models import Section
        from django.db.models import Count

        queryset = Section.objects.filter(
            grade_level__active=True,
            # active=True
        ).select_related(
            'grade_level'
        ).prefetch_related(
            'section_subjects__subject',
            'section_fees__general_fee'
        ).annotate(
            student_count=Count('enrollments', distinct=True)
        )

        sections = []
        for section in queryset:
            subjects = [
                {
                    'id': str(ss.id),
                    'section': {
                        'id': str(section.id),
                        'name': section.name,
                    },
                    'subject': {
                        'id': str(ss.subject.id),
                        'name': ss.subject.name,
                    },
                    'grade_level': {
                        'id': str(section.grade_level.id),
                        'name': section.grade_level.name,
                        'level': section.grade_level.level,
                    },
                    'active': ss.active,
                    'can_delete': not section_subject_has_grades(ss),
                }
                for ss in section.section_subjects.all()
            ]

            fees = [
                {
                    'id': str(sf.id),
                    'name': sf.general_fee.name,
                    'amount': str(sf.amount),
                    'active': sf.active,
                    'section': str(section.id),
                    'general_fee': {
                        'id': str(sf.general_fee.id),
                        'name': sf.general_fee.name,
                        'description': sf.general_fee.description or '',
                        'student_target': sf.general_fee.student_target,
                        'active': sf.general_fee.active,
                    },
                    'student_target': sf.general_fee.student_target,
                }
                for sf in section.section_fees.all()
            ]

            sections.append({
                'id': str(section.id),
                'name': section.name,
                'description': section.description or '',
                'max_capacity': section.max_capacity,
                'active': section.active,
                'students': section.student_count,
                'grade_level_id': str(section.grade_level.id),
                'grade_level': {
                    'id': str(section.grade_level.id),
                    'name': section.grade_level.name,
                    'short_name': section.grade_level.short_name,
                    'level': section.grade_level.level,
                    'active': section.grade_level.active,
                },
                'subjects': subjects,
                'fees': fees,
            })

        sections.sort(key=lambda x: (x['grade_level']['level'], x['name']))

        cache.set(cache_key, sections, DataCache._get_timeout())
        return sections

    @staticmethod
    def invalidate_sections(
        request=None,
    ):
        """
        Invalidate sections cache for a tenant.
        If academic_year_id is provided, only invalidate that specific cache.
        Otherwise, invalidate all section caches for the tenant.
        """
        cache_key = DataCache._get_cache_key("sections", "all", request)
        cache.delete(cache_key)
        logger.debug(f"Invalidated cache: all sections for scope {cache_key}")

    # ==================== ACADEMIC YEARS ====================
    
    @staticmethod
    def get_academic_years(force_refresh: bool = False, request=None) -> List[Dict[str, Any]]:
        """Get all academic years for a tenant."""
        from academics.models import AcademicYear
        
        def query():
            return list(
                AcademicYear.objects.all()
                .order_by('-start_date')
                .values('id', 'name', 'start_date', 'end_date', 'current', 'status')
            )
        
        return DataCache._get_cached_data(
            "academic_years",
            query,
            force_refresh=force_refresh,
            request=request,
        )

    @staticmethod
    def get_current_academic_year(
        force_refresh: bool = False,
        request=None,
    ) -> Optional[Dict[str, Any]]:
        """Get the current academic year for a tenant."""
        from academics.models import AcademicYear
        from datetime import date as date_class
        
        def query():
            try:
                from academics.serializers import AcademicYearSerializer
                academic_year = AcademicYear.objects.filter(
                    current=True
                ).first()
                if academic_year:
                    # Use serializer to include semesters, duration and stats
                    serializer = AcademicYearSerializer(
                        academic_year,
                        context={"request": request, "include_stats": True}
                    )
                    return serializer.data
            except Exception as e:
                logger.error(f"Error serializing academic year: {e}", exc_info=True)
            
            # Fallback: return data with duration calculation
            try:
                from academics.serializers import AcademicYearSerializer
                academic_year = AcademicYear.objects.filter(current=True).first()
                if academic_year:
                    # Calculate duration
                    total_days = (academic_year.end_date - academic_year.start_date).days + 1
                    today = date_class.today()
                    days_elapsed = (today - academic_year.start_date).days
                    days_elapsed = max(0, min(days_elapsed, total_days))
                    completion_percentage = int((days_elapsed / total_days * 100)) if total_days > 0 else 0
                    
                    # Try to get semesters
                    semesters = []
                    try:
                        from academics.serializers import SemesterSerializer
                        today = date_class.today()
                        f = (
                            Q(start_date__gte=academic_year.start_date) & Q(end_date__lte=academic_year.end_date)
                        ) | Q(start_date__lte=today) & Q(end_date__gte=today)
                        sem_qs = academic_year.semesters.filter(f)
                        semesters = SemesterSerializer(sem_qs, many=True).data
                    except:
                        semesters = []
                    
                    return {
                        "id": str(academic_year.id),
                        "name": academic_year.name,
                        "start_date": str(academic_year.start_date),
                        "end_date": str(academic_year.end_date),
                        "current": academic_year.current,
                        "status": academic_year.status,
                        "semesters": semesters,
                        "duration": {
                            "total_days": total_days,
                            "days_elapsed": days_elapsed,
                            "completion_percentage": completion_percentage,
                        }
                    }
            except Exception as e:
                logger.error(f"Error fetching current academic year fallback: {e}", exc_info=True)
            
            return None
        
        return DataCache._get_cached_data(
            "current_academic_year",
            query,
            force_refresh=force_refresh,
            request=request,
        )

    @staticmethod
    def invalidate_academic_years(request=None):
        """Invalidate both academic years and current academic year caches."""
        DataCache._invalidate_cache("academic_years", request=request)
        DataCache._invalidate_cache("current_academic_year", request=request)

    # ==================== SEMESTERS ====================
    
    @staticmethod
    def get_semesters(
        academic_year_id: Optional[str] = None,
        force_refresh: bool = False,
        request=None,
    ) -> List[Dict[str, Any]]:
        """Get semesters for a tenant, optionally filtered by academic year."""
        from academics.models import Semester
        
        suffix = f"ay_{academic_year_id}" if academic_year_id else "all"
        
        def query():
            queryset = Semester.objects.all().select_related('academic_year')
            if academic_year_id:
                queryset = queryset.filter(academic_year_id=academic_year_id)
            
            return list(
                queryset.values(
                    'id', 'name', 'start_date', 'end_date', 'academic_year_id', 'academic_year__name'
                ).order_by('start_date')
            )
        
        return DataCache._get_cached_data(
            "semesters",
            query,
            suffix,
            force_refresh,
            request=request,
        )

    @staticmethod
    def invalidate_semesters(academic_year_id: Optional[str] = None, request=None):
        """Invalidate semesters cache."""
        if academic_year_id:
            DataCache._invalidate_cache(
                "semesters",
                f"ay_{academic_year_id}",
                "all",
                request=request,
            )
        else:
            DataCache._invalidate_cache("semesters", "all", request=request)

    # ==================== MARKING PERIODS ====================
    
    @staticmethod
    def get_marking_periods(
        semester_id: Optional[str] = None,
        force_refresh: bool = False,
        request=None,
    ) -> List[Dict[str, Any]]:
        """Get marking periods, optionally filtered by semester."""
        suffix = f"sem_{semester_id}" if semester_id else "all"
        cache_key = DataCache._get_cache_key("marking_periods", suffix, request)
        
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache HIT: marking_periods for scope {cache_key}")
                return cached
        
            logger.debug(f"Cache MISS: marking_periods for scope {cache_key}")
        
        from academics.models import MarkingPeriod
        
        queryset = MarkingPeriod.objects.all().select_related('semester', 'semester__academic_year')
        
        if semester_id:
            queryset = queryset.filter(semester_id=semester_id)
        
        marking_periods = list(
            queryset.values(
                'id', 'name', 'short_name', 'description',
                'start_date', 'end_date', 'semester_id', 'semester__name',
                'semester__academic_year_id', 'semester__academic_year__name'
            ).order_by('start_date')
        )
        
        cache.set(cache_key, marking_periods, DataCache._get_timeout())
        return marking_periods

    @staticmethod
    def invalidate_marking_periods(semester_id: Optional[str] = None, request=None):
        """Invalidate marking periods cache."""
        if semester_id:
            suffix = f"sem_{semester_id}"
            cache_key = DataCache._get_cache_key("marking_periods", suffix, request)
            cache.delete(cache_key)
        
        cache_key = DataCache._get_cache_key("marking_periods", "all", request)
        cache.delete(cache_key)
        logger.debug(f"Invalidated cache: marking_periods for scope {cache_key}")

    # ==================== SUBJECTS ====================
    
    @staticmethod
    def get_subjects(force_refresh: bool = False, request=None) -> List[Dict[str, Any]]:
        """Get all subjects for a tenant with computed deletion logic fields."""
        from academics.models import Subject
        from grading.models import Grade, GradeBook
        
        def query():
            subjects = Subject.objects.all().order_by('name')
            result = []
            
            for subject in subjects:
                # Compute grade-related flags
                has_gradebooks = GradeBook.objects.filter(subject=subject).exists()
                has_grade_records = Grade.objects.filter(subject=subject).exists()
                has_grades = has_gradebooks or has_grade_records
                has_scored_grades = Grade.objects.filter(subject=subject, score__isnull=False).exists()
                
                # Compute deletion logic flags
                can_delete = not has_grades
                can_force_delete = has_grades and not has_scored_grades
                must_deactivate = has_scored_grades
                
                result.append({
                    'id': str(subject.id),
                    'name': subject.name,
                    'description': subject.description,
                    'active': subject.active,
                    'status': 'active' if subject.active else 'disabled',
                    # Computed fields for deletion logic
                    'can_delete': can_delete,
                    'can_force_delete': can_force_delete,
                    'must_deactivate': must_deactivate,
                    'has_grades': has_grades,
                    'has_scored_grades': has_scored_grades,
                })
            
            return result
        
        return DataCache._get_cached_data(
            "subjects",
            query,
            force_refresh=force_refresh,
            request=request,
        )

    @staticmethod
    def invalidate_subjects(request=None):
        """Invalidate subjects cache."""
        DataCache._invalidate_cache("subjects", request=request)

    # ==================== PAYMENT METHODS ====================
    
    @staticmethod
    def get_payment_methods(force_refresh: bool = False, request=None) -> List[Dict[str, Any]]:
        """Get all payment methods for a tenant."""
        from finance.models import PaymentMethod
        
        def query():
            return list(
                PaymentMethod.objects.all()
                .order_by('name')
                .values('id', 'name', 'description', 'is_editable')
            )
        
        return DataCache._get_cached_data(
            "payment_methods",
            query,
            force_refresh=force_refresh,
            request=request,
        )

    @staticmethod
    def invalidate_payment_methods(request=None):
        """Invalidate payment methods cache."""
        DataCache._invalidate_cache("payment_methods", request=request)

    # ==================== TRANSACTION TYPES ====================
    
    @staticmethod
    def get_transaction_types(
        include_hidden: bool = False,
        force_refresh: bool = False,
        request=None,
    ) -> List[Dict[str, Any]]:
        """Get transaction types for a tenant."""
        from finance.models import TransactionType
        
        suffix = "with_hidden" if include_hidden else "visible"
        
        def query():
            queryset = TransactionType.objects.all()
            if not include_hidden:
                queryset = queryset.filter(is_hidden=False)
            
            return list(
                queryset.order_by('type', 'name').values(
                    'id', 'name', 'description', 'type_code', 'type', 
                    'is_hidden', 'is_editable'
                )
            )
        
        return DataCache._get_cached_data(
            "transaction_types",
            query,
            suffix,
            force_refresh,
            request=request,
        )

    @staticmethod
    def invalidate_transaction_types(request=None):
        """Invalidate transaction types cache."""
        DataCache._invalidate_cache(
            "transaction_types",
            "visible",
            "with_hidden",
            request=request,
        )

    # ==================== INSTALLMENTS ====================
    
    @staticmethod
    def get_installments(
        academic_year_id: Optional[str] = None,
        force_refresh: bool = False,
        request=None,
    ) -> List[Dict[str, Any]]:
        """Get payment installments, optionally filtered by academic year."""
        suffix = f"ay_{academic_year_id}" if academic_year_id else "all"
        cache_key = DataCache._get_cache_key("installments", suffix, request)
        
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache HIT: installments for tenant")
                return cached
        
        logger.debug(f"Cache MISS: installments for tenant")
        
        from finance.models import PaymentInstallment
        
        queryset = PaymentInstallment.objects.all().select_related('academic_year')
        
        if academic_year_id:
            queryset = queryset.filter(academic_year_id=academic_year_id)
        
        installments = list(
            queryset.order_by('due_date').values(
                'id', 'name', 'due_date', 'value', 
                'academic_year_id', 'academic_year__name'
            )
        )
        
        cache.set(cache_key, installments, DataCache._get_timeout())
        return installments

    @staticmethod
    def invalidate_installments(academic_year_id: Optional[str] = None, request=None):
        """Invalidate installments cache."""
        if academic_year_id:
            suffix = f"ay_{academic_year_id}"
            cache_key = DataCache._get_cache_key("installments", suffix, request)
            cache.delete(cache_key)
        
        cache_key = DataCache._get_cache_key("installments", "all", request)
        cache.delete(cache_key)
        logger.debug(f"Invalidated cache: installments for scope {cache_key}")

    # ==================== BULK OPERATIONS ====================
    
    @staticmethod
    def invalidate_all(request=None):
        """Invalidate all reference data caches for a tenant."""
        DataCache.invalidate_divisions(request=request)
        DataCache.invalidate_grade_levels(request=request)
        DataCache.invalidate_sections(request=request)
        DataCache.invalidate_academic_years(request=request)
        DataCache.invalidate_semesters(request=request)
        DataCache.invalidate_marking_periods(request=request)
        DataCache.invalidate_subjects(request=request)
        DataCache.invalidate_payment_methods(request=request)
        DataCache.invalidate_transaction_types(request=request)
        DataCache.invalidate_installments(request=request)
        logger.debug("Invalidated ALL reference data caches for tenant scope")

    @staticmethod
    def get_all_reference_data(
        academic_year_id: Optional[str] = None,
        force_refresh: bool = False,
        request=None,
    ) -> Dict[str, Any]:
        """
        Get all reference data for a tenant in a single call.
        Useful for dashboard initialization.
        """
        return {
            'divisions': DataCache.get_divisions(force_refresh, request=request),
            'grade_levels': DataCache.get_grade_levels(force_refresh, request=request),
            'sections': DataCache.get_sections(academic_year_id, force_refresh, request=request),
            'academic_years': DataCache.get_academic_years(force_refresh, request=request),
            'current_academic_year': DataCache.get_current_academic_year(force_refresh, request=request),
            'semesters': DataCache.get_semesters(academic_year_id, force_refresh, request=request),
            'subjects': DataCache.get_subjects(force_refresh, request=request),
            'payment_methods': DataCache.get_payment_methods(force_refresh, request=request),
            'transaction_types': DataCache.get_transaction_types(False, force_refresh, request=request),
            'installments': DataCache.get_installments(academic_year_id, force_refresh, request=request),
        }

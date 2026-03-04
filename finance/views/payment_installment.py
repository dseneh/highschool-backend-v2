import logging
import time
from datetime import datetime
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, Sum
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import FinanceAccessPolicy

logger = logging.getLogger(__name__)


def get_cache_info():
    """Get information about the cache backend for debugging"""
    error = None
    try:
        cache_backend = cache.__class__.__name__
        cache_location = getattr(cache, "_cache", {}).get("location", "unknown")

        # Test cache connectivity
        test_key = "payment_installment:test:connectivity"
        test_value = "test_value_123"

        try:
            cache.set(test_key, test_value, 60)
            retrieved = cache.get(test_key)
            cache.delete(test_key)
            is_working = retrieved == test_value
            if not is_working:
                error = f"Cache test failed: expected '{test_value}', got '{retrieved}'"
        except Exception as e:
            is_working = False
            error = str(e)

        return {
            "backend": cache_backend,
            "location": cache_location,
            "working": is_working,
            "error": error,
        }
    except Exception as e:
        return {
            "backend": "unknown",
            "location": "unknown",
            "working": False,
            "error": str(e),
        }


from common.utils import (
    create_model_data,
    update_model_fields,
    validate_required_fields,
)
from academics.models import AcademicYear
from finance.models import PaymentInstallment
from finance.serializers import (
    PaymentInstallmentDetailSerializer,
    PaymentInstallmentSerializer,
)

# Cache constants
# Installments are created once per academic year and rarely change,
# so we can cache them for much longer. Cache is invalidated on create/update/delete.
INSTALLMENT_CACHE_TIMEOUT = 86400  # 24 hours - installments rarely change
ACADEMIC_YEAR_CACHE_TIMEOUT = (
    3600  # 1 hour - academic year data changes more frequently
)

ACADEMIC_YEAR_CACHE_KEY = "payment_installment:academic_year:{academic_year_id}"
INSTALLMENT_LIST_CACHE_KEY = (
    "payment_installment:list:{academic_year_id}:{active}"
)
INSTALLMENT_DETAIL_CACHE_KEY = "payment_installment:detail:{installment_id}"
INSTALLMENT_CUMULATIVE_CACHE_KEY = (
    "payment_installment:cumulative:{academic_year_id}:{sequence}"
)


def sync_payment_summaries_after_installment_change(academic_year_id):
    """
    Recalculate payment summaries for all enrollments in an academic year
    after installments are created/updated/deleted.

    Uses smart sync/async: synchronous for small datasets (< 50 enrollments),
    asynchronous for large datasets to avoid blocking API responses.

    Args:
        academic_year_id: Academic year ID to recalculate summaries for
    """
    try:
        from students.models import Enrollment

        # Import here to avoid circular dependency - handle ImportError gracefully
        try:
            from finance.tasks import (
                recalc_payment_summaries_async,
                recalc_payment_summaries_for_academic_year,
            )

            use_tasks_module = True
        except ImportError:
            # Fallback if tasks module has import issues
            use_tasks_module = False
            logger.warning(
                f"Could not import from finance.tasks, will use direct implementation"
            )

        # Check enrollment count - if small (< 50), do it synchronously for immediate update
        enrollment_count = Enrollment.objects.filter(
            academic_year_id=academic_year_id, status="active"
        ).count()

        if use_tasks_module:
            # Use tasks module functions
            if enrollment_count < 50:
                # Small dataset - update synchronously for immediate effect
                logger.info(
                    f"Updating payment summaries synchronously for academic year "
                    f"{academic_year_id} ({enrollment_count} enrollments)"
                )
                recalc_payment_summaries_for_academic_year(academic_year_id)
            else:
                # Large dataset - update asynchronously
                recalc_payment_summaries_async(academic_year_id)
                logger.info(
                    f"Queued background task to recalculate payment summaries "
                    f"for academic year {academic_year_id} ({enrollment_count} enrollments)"
                )
        else:
            # Fallback: direct implementation without tasks module
            from finance.utils import calculate_student_payment_summary
            from academics.models import AcademicYear
            import threading

            academic_year = AcademicYear.objects.get(id=academic_year_id)
            enrollments = Enrollment.objects.filter(
                academic_year=academic_year, status="active"
            ).select_related("student", "academic_year")

            if enrollment_count < 50:
                # Small dataset - update synchronously
                logger.info(
                    f"Updating payment summaries synchronously (direct) for academic year "
                    f"{academic_year_id} ({enrollment_count} enrollments)"
                )
                for enrollment in enrollments:
                    try:
                        calculate_student_payment_summary(enrollment, academic_year)
                    except Exception as e:
                        logger.warning(
                            f"Failed to calculate payment summary for enrollment "
                            f"{enrollment.id}: {e}"
                        )
            else:
                # Large dataset - update asynchronously using threading
                def background_work():
                    try:
                        for enrollment in enrollments:
                            try:
                                calculate_student_payment_summary(
                                    enrollment, academic_year
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to calculate payment summary for enrollment "
                                    f"{enrollment.id}: {e}"
                                )
                    except Exception as e:
                        logger.error(
                            f"Error in background payment summary recalculation: {e}",
                            exc_info=True,
                        )

                thread = threading.Thread(target=background_work)
                thread.daemon = True
                thread.start()
                logger.info(
                    f"Started background thread to recalculate payment summaries "
                    f"for academic year {academic_year_id} ({enrollment_count} enrollments)"
                )
    except Exception as e:
        logger.error(
            f"Failed to recalculate payment summaries for "
            f"academic year {academic_year_id}: {e}",
            exc_info=True,
        )


def validate_installments_data(installments_data, academic_year, existing_installments_dict=None):
    """
    Centralized validation for installment data.
    
    Args:
        installments_data: List of installment dictionaries to validate
        academic_year: AcademicYear object
        existing_installments_dict: Dict of existing installments by ID (for updates)
    
    Returns:
        (validated_items, error_response) tuple
    """
    if not installments_data:
        return [], Response(
            {"detail": "No installments provided"},
            status=400,
        )
    
    academic_year_start = academic_year.start_date
    academic_year_end = academic_year.end_date
    existing_installments_dict = existing_installments_dict or {}
    
    validated_items = []
    errors = []
    parsed_due_dates = {}
    
    # Pre-parse all due dates
    for idx, item in enumerate(installments_data):
        if isinstance(item, dict) and "due_date" in item:
            try:
                due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
                parsed_due_dates[idx] = due_date
            except (ValueError, TypeError):
                pass
    
    # Validate individual items
    for idx, item_data in enumerate(installments_data):
        if not isinstance(item_data, dict):
            errors.append({
                "index": idx,
                "error": "Each installment must be an object",
            })
            continue
        
        # For updates, id is required
        if existing_installments_dict is not None and "id" not in item_data:
            errors.append({
                "index": idx,
                "error": "Each installment must have an 'id' field",
            })
            continue
        
        # Validate value if present
        if "value" in item_data:
            try:
                value = float(item_data["value"])
                if value <= 0 or value > 100:
                    errors.append({
                        "index": idx,
                        "error": "Percentage must be between 0 and 100 (exclusive of 0)",
                    })
                    continue
            except (ValueError, TypeError):
                errors.append({
                    "index": idx,
                    "error": "Invalid value. Must be a number",
                })
                continue
        
        # Validate due_date if present
        if "due_date" in item_data:
            due_date = parsed_due_dates.get(idx)
            if due_date is None:
                errors.append({
                    "index": idx,
                    "error": "Invalid due_date format. Use YYYY-MM-DD",
                })
                continue
            
            if due_date < academic_year_start or due_date > academic_year_end:
                errors.append({
                    "index": idx,
                    "error": f"Due date must be within {academic_year_start} to {academic_year_end}",
                })
                continue
        
        # Validate sequence if present
        if "sequence" in item_data:
            try:
                sequence = int(item_data["sequence"])
                if sequence < 0:
                    raise ValueError("Sequence must be positive")
            except (ValueError, TypeError):
                errors.append({
                    "index": idx,
                    "error": "Invalid sequence. Must be a positive integer",
                })
                continue
        
        validated_items.append((idx, item_data))
    
    if errors:
        error_messages = [f"Index {e['index']}: {e['error']}" for e in errors]
        return [], Response(
            {"detail": f"Validation errors: {'; '.join(error_messages)}"},
            status=400,
        )
    
    return validated_items, None


def validate_dates_no_overlap(installments_data, academic_year, exclude_ids=None):
    """
    Validate that due dates don't overlap within an academic year.
    
    Args:
        installments_data: List of installment dictionaries
        academic_year: AcademicYear object
        exclude_ids: Set of IDs to exclude from existing date check
    
    Returns:
        error_response if overlapping dates found, else None
    """
    exclude_ids = exclude_ids or set()
    
    # Collect all dates being set in this request
    request_dates = {}
    for idx, item in enumerate(installments_data):
        if isinstance(item, dict) and "due_date" in item:
            try:
                due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
                if due_date in request_dates:
                    return Response(
                        {
                            "detail": f"Duplicate due date '{due_date}' in request. Each installment must have a unique due date.",
                        },
                        status=400,
                    )
                request_dates[due_date] = idx
            except (ValueError, TypeError):
                pass
    
    # Check for overlaps with existing dates in academic year
    if request_dates:
        existing_dates = PaymentInstallment.objects.filter(
            academic_year=academic_year,
            active=True
        ).exclude(id__in=exclude_ids).values_list("due_date", flat=True)
        
        for existing_date in existing_dates:
            if existing_date in request_dates:
                return Response(
                    {
                        "detail": f"Due date '{existing_date}' already exists. Each installment must have a unique due date.",
                    },
                    status=400,
                )
    
    return None


def validate_total_percentage(installments_data, academic_year, exclude_ids=None):
    """
    Validate that total percentage equals 100%.
    
    For creates: all new items must sum to 100%
    For updates: new items + unchanged items must sum to 100%
    
    Args:
        installments_data: List of installment dictionaries
        academic_year: AcademicYear object
        exclude_ids: Set of IDs being updated (for UPDATE operations)
    
    Returns:
        error_response if total != 100%, else None
    """
    exclude_ids = exclude_ids or set()
    
    # Build map of values being set in this request
    values_map = {}
    for item in installments_data:
        if isinstance(item, dict):
            if "id" in item and "value" in item:
                values_map[str(item["id"])] = float(item["value"])
            elif "id" in item and "value" not in item:
                # For updates where value isn't changing, we'll add existing value below
                pass
    
    # Calculate total: updated items + unchanged items
    total = 0.0
    
    # Add all active installments, using updated value if provided
    all_active = PaymentInstallment.objects.filter(
        academic_year=academic_year,
        active=True
    )
    
    for inst in all_active:
        inst_id = str(inst.id)
        if inst_id in values_map:
            total += values_map[inst_id]
        elif inst_id not in exclude_ids:
            # Keep existing value if not being updated
            total += float(inst.value)
        # If in exclude_ids but not in values_map, skip (being deleted or not updating)
    
    # For creates (no exclude_ids), just sum the request values
    if not exclude_ids:
        total = sum(float(item.get("value", 0)) for item in installments_data if isinstance(item, dict) and "value" in item)
    
    if abs(total - 100.0) > 0.01:
        return Response(
            {
                "detail": f"Total percentage of all installments must equal 100%. Current total: {total:.2f}%",
            },
            status=400,
        )
    
    return None


def clear_installment_cache(
    academic_year_id=None, installment_ids=None
):
    """Clear all cached data related to installments for an academic year
    Also clears payment plan and payment status caches for affected enrollments
    """
    from django.core.cache import cache

    try:
        # Clear list caches (all combinations)
        if academic_year_id:
            for active in ["True", "False"]:
                for ay_id in [academic_year_id, "all"]:
                    cache_key = INSTALLMENT_LIST_CACHE_KEY.format(
                        academic_year_id=ay_id, active=active
                    )
                    cache.delete(cache_key)
                    logger.debug(f"Cleared list cache: {cache_key}")

        # Clear individual installment detail caches
        if installment_ids:
            for inst_id in installment_ids:
                cache_key = INSTALLMENT_DETAIL_CACHE_KEY.format(installment_id=inst_id)
                cache.delete(cache_key)
                logger.debug(f"Cleared detail cache: {cache_key}")
        elif academic_year_id:
            # Use pattern deletion for Redis (same pattern as permission cache)
            if hasattr(cache, "delete_pattern"):
                pattern = INSTALLMENT_DETAIL_CACHE_KEY.format(installment_id="*")
                cache.delete_pattern(pattern)
                logger.debug(f"Cleared detail caches using pattern: {pattern}")

        # Clear cumulative percentage caches for this academic year
        if academic_year_id:
            # Delete all cumulative caches using pattern (Redis)
            if hasattr(cache, "delete_pattern"):
                pattern = INSTALLMENT_CUMULATIVE_CACHE_KEY.format(
                    academic_year_id=academic_year_id, sequence="*"
                )
                cache.delete_pattern(pattern)
                logger.debug(f"Cleared cumulative caches using pattern: {pattern}")

        # Clear payment plan and payment status caches for all enrollments in this academic year
        # When installments change, all payment plans/statuses for that academic year need to be recalculated
        if academic_year_id:
            # Try pattern deletion first (works with Redis)
            if hasattr(cache, "delete_pattern"):
                try:
                    # Clear all payment plans for this academic year
                    plan_pattern = f"payment_plan:*:{academic_year_id}"
                    cache.delete_pattern(plan_pattern)
                    logger.debug(
                        f"Cleared payment plan caches using pattern: {plan_pattern}"
                    )

                    # Clear all payment statuses for this academic year
                    status_pattern = f"payment_status:*:{academic_year_id}"
                    cache.delete_pattern(status_pattern)
                    logger.debug(
                        f"Cleared payment status caches using pattern: {status_pattern}"
                    )
                except Exception as pattern_error:
                    logger.warning(
                        f"Pattern deletion failed, falling back to enrollment-based clearing: {pattern_error}"
                    )
                    # Fallback: query enrollments and clear individually
                    from students.models import Enrollment

                    enrollments = Enrollment.objects.filter(
                        academic_year_id=academic_year_id, status="active"
                    ).values_list("id", flat=True)

                    for enrollment_id in enrollments:
                        plan_key = f"payment_plan:{enrollment_id}:{academic_year_id}"
                        status_key = (
                            f"payment_status:{enrollment_id}:{academic_year_id}"
                        )
                        cache.delete(plan_key)
                        cache.delete(status_key)

                    logger.debug(
                        f"Cleared payment caches for {enrollments.count()} enrollments in academic year {academic_year_id}"
                    )
            else:
                # No pattern deletion support, query enrollments and clear individually
                from students.models import Enrollment

                enrollments = Enrollment.objects.filter(
                    academic_year_id=academic_year_id, status="active"
                ).values_list("id", flat=True)

                for enrollment_id in enrollments:
                    plan_key = f"payment_plan:{enrollment_id}:{academic_year_id}"
                    status_key = f"payment_status:{enrollment_id}:{academic_year_id}"
                    cache.delete(plan_key)
                    cache.delete(status_key)

                logger.debug(
                    f"Cleared payment caches for {enrollments.count()} enrollments in academic year {academic_year_id}"
                )
    except Exception as e:
        logger.error(f"Error clearing installment cache: {e}")
        # Don't fail the request if cache clearing fails


def clear_student_payment_cache(
    enrollment_id=None, academic_year_id=None, student_id=None
):
    """
    Clear payment plan and payment status caches for a specific enrollment or student.
    Used when transactions are created/updated/deleted.

    Args:
        enrollment_id: Specific enrollment ID to clear (most specific)
        academic_year_id: Academic year ID - clears all enrollments in that year
        student_id: Student ID - clears all enrollments for that student
    """
    from django.core.cache import cache

    try:
        if enrollment_id and academic_year_id:
            # Clear specific enrollment's payment plan and status
            plan_key = f"payment_plan:{enrollment_id}:{academic_year_id}"
            status_key = f"payment_status:{enrollment_id}:{academic_year_id}"
            cache.delete(plan_key)
            cache.delete(status_key)
            logger.debug(
                f"Cleared payment cache for enrollment {enrollment_id} in academic year {academic_year_id}"
            )
        elif academic_year_id:
            # Clear all payment plans/statuses for this academic year
            if hasattr(cache, "delete_pattern"):
                plan_pattern = f"payment_plan:*:{academic_year_id}"
                status_pattern = f"payment_status:*:{academic_year_id}"
                cache.delete_pattern(plan_pattern)
                cache.delete_pattern(status_pattern)
                logger.debug(
                    f"Cleared all payment caches for academic year {academic_year_id}"
                )
        elif student_id:
            # Clear all payment plans/statuses for this student (across all academic years)
            if hasattr(cache, "delete_pattern"):
                plan_pattern = f"payment_plan:*:*"  # Would need enrollment IDs, so this is less efficient
                status_pattern = f"payment_status:*:*"
                # For student_id, we'd need to query enrollments first, so this is handled in the signal
                logger.debug(
                    f"Note: Clearing payment cache for student {student_id} requires enrollment lookup"
                )
    except Exception as e:
        logger.error(f"Error clearing student payment cache: {e}")
        # Don't fail the request if cache clearing fails


class PaymentInstallmentListView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to list all payment installments or create a new payment installment.
    Supports filtering by academic_year, etc.
    """

    def get(self, request, academic_year_id=None):
        """List all payment installments for a school"""
        start_time = time.time()

        # Get optional filters
        active_filter = request.query_params.get("active", "true")
        active_bool = (
            active_filter.lower() in ["true", "1", "yes"]
            if active_filter is not None
            else True
        )

        cache_key = INSTALLMENT_LIST_CACHE_KEY.format(
            academic_year_id=academic_year_id or "all",
            active=str(active_bool),
        )

        cache_start = time.time()
        cached_data = cache.get(cache_key)
        cache_time = (time.time() - cache_start) * 1000

        if cached_data is not None:
            total_time = (time.time() - start_time) * 1000
            logger.info(
                f"Cache HIT for installment list: {cache_key} | "
                f"Cache lookup: {cache_time:.2f}ms | Total: {total_time:.2f}ms"
            )
            return Response(cached_data)

        logger.debug(
            f"Cache MISS for installment list: {cache_key} (lookup took {cache_time:.2f}ms)"
        )

        # Build optimized query with select_related and only() to limit fields
        installments = PaymentInstallment.objects.select_related("academic_year").all()

        if academic_year_id:
            installments = installments.filter(academic_year_id=academic_year_id)

        if active_filter is not None:
            installments = installments.filter(active=active_bool)

        installments = installments.order_by("academic_year", "sequence")

        # OPTIMIZATION: Pre-calculate cumulative percentages in a single pass
        # This eliminates N queries (one per installment) in the serializer
        installments_list = list(installments)
        cumulative_map = {}

        # Group by academic_year and get all active installments for cumulative calculation
        academic_year_ids = set(inst.academic_year.id for inst in installments_list)

        # Fetch all active installments for these academic years to calculate cumulative correctly
        # (cumulative should include all active installments up to sequence, not just filtered ones)
        all_active_installments = (
            PaymentInstallment.objects.filter(
                academic_year_id__in=academic_year_ids, active=True
            )
            .select_related("academic_year")
            .order_by("academic_year", "sequence")
        )

        # Group by academic year and calculate cumulative
        by_academic_year = {}
        for inst in all_active_installments:
            ay_id = inst.academic_year.id
            if ay_id not in by_academic_year:
                by_academic_year[ay_id] = []
            if inst.sequence is not None:
                by_academic_year[ay_id].append(inst)

        # Calculate cumulative for each academic year
        for ay_id, ay_installments in by_academic_year.items():
            # Already sorted by sequence from query
            cumulative = 0.0
            for inst in ay_installments:
                cumulative += float(inst.value)
                cumulative_map[inst.id] = cumulative

        # Pass cumulative map to serializer via context
        serializer = PaymentInstallmentSerializer(
            installments_list,
            many=True,
            context={"cumulative_percentages": cumulative_map},
        )
        response_data = serializer.data

        # Cache the response for 24 hours (installments rarely change)
        # Cache is invalidated on create/update/delete operations (same pattern as permission cache)
        cache_set_start = time.time()
        cache.set(cache_key, response_data, INSTALLMENT_CACHE_TIMEOUT)
        cache_time = (time.time() - cache_set_start) * 1000

        total_time = (time.time() - start_time) * 1000
        logger.info(
            f"Cache SET for installment list: {cache_key} | "
            f"Cache write: {cache_time:.2f}ms | Total: {total_time:.2f}ms | "
            f"Items: {len(response_data)}"
        )

        return Response(response_data)

    def post(self, request, academic_year_id):
        """
        Create payment installment(s). Supports both single and bulk creation.

        Single: {"name": "...", "value": 50, "due_date": "2025-10-01", ...}
        Bulk: [{"name": "...", "value": 50, ...}, {"name": "...", "value": 75, ...}]
        or {"installments": [{"name": "...", ...}, ...]}
        """
        req_data = request.data

        # Validate academic_year (with caching - same pattern as permission cache)
        cache_key = ACADEMIC_YEAR_CACHE_KEY.format(academic_year_id=academic_year_id)
        academic_year = cache.get(cache_key)

        if academic_year is None:
            try:
                academic_year = AcademicYear.objects.get(
                    id=academic_year_id
                )
                # Cache for 1 hour
                cache.set(cache_key, academic_year, ACADEMIC_YEAR_CACHE_TIMEOUT)
            except AcademicYear.DoesNotExist:
                return Response(
                    {
                        "detail": "Academic year not found"
                    },
                    status=400,
                )

        # Support both single object and bulk (list or object with "installments" key)
        if isinstance(req_data, list):
            installments_data = req_data
        elif isinstance(req_data, dict) and "installments" in req_data:
            installments_data = req_data["installments"]
        else:
            # Single installment
            installments_data = [req_data]

        if not installments_data:
            return Response(
                {"detail": "No installments provided"},
                status=400,
            )

        # Cache academic year dates to avoid repeated access
        academic_year_start = academic_year.start_date
        academic_year_end = academic_year.end_date

        # Pre-parse and validate due dates once (optimization)
        parsed_due_dates = {}
        if len(installments_data) > 1:
            # Validate that percentages sum to exactly 100% (for bulk operations)
            total_percentage = 0.0
            for item in installments_data:
                if isinstance(item, dict) and "value" in item:
                    try:
                        total_percentage += float(item.get("value", 0))
                    except (ValueError, TypeError):
                        pass  # Will be caught in individual validation

            # Must be exactly 100.0 (no tolerance for floating point differences)
            if abs(total_percentage - 100.0) > 0.01:
                return Response(
                    {
                        "detail": f"Total percentage of all installments must equal exactly 100%. Current total: {total_percentage}%"
                    },
                    status=400,
                )

            # Validate that all due dates are unique (at least one day apart)
            due_dates_set = set()
            for idx, item in enumerate(installments_data):
                if isinstance(item, dict) and "due_date" in item:
                    try:
                        due_date = datetime.strptime(
                            item["due_date"], "%Y-%m-%d"
                        ).date()
                        if due_date in due_dates_set:
                            return Response(
                                {
                                    "detail": f"Duplicate due date '{due_date}'. Each installment must have a unique due date (at least one day apart)."
                                },
                                status=400,
                            )
                        due_dates_set.add(due_date)
                        parsed_due_dates[idx] = due_date
                    except (ValueError, TypeError):
                        pass  # Will be caught in individual validation

        created_installments = []
        errors = []

        def validate_installment_data(item_data, index=None):
            """Validate a single installment data"""
            required_fields = ["value", "due_date"]
            missing = [f for f in required_fields if f not in item_data]
            if missing:
                return None, f"Missing required fields: {', '.join(missing)}"

            # Validate value
            try:
                value = float(item_data.get("value", 0))
                if value < 0 or value > 100:
                    return None, "Percentage value must be between 0 and 100"
            except (ValueError, TypeError):
                return None, "Invalid value. Must be a number between 0 and 100"

            # Validate due_date - use cached parsed date if available
            if index in parsed_due_dates:
                due_date = parsed_due_dates[index]
            else:
                try:
                    due_date = datetime.strptime(
                        item_data["due_date"], "%Y-%m-%d"
                    ).date()
                except (ValueError, KeyError):
                    return None, "Invalid due_date format. Use YYYY-MM-DD"

            # Validate due_date is within academic year (use cached dates)
            if due_date < academic_year_start:
                return (
                    None,
                    f"Due date ({due_date}) cannot be before academic year start date ({academic_year_start})",
                )

            if due_date > academic_year_end:
                return (
                    None,
                    f"Due date ({due_date}) cannot be after academic year end date ({academic_year_end})",
                )

            # Build data dict
            data = {
                "academic_year": academic_year,
                "description": item_data.get("description", ""),
                "value": value,
                "due_date": due_date,
                "active": item_data.get("active", True),
            }

            # Only set name if provided, otherwise let the model auto-generate it
            if "name" in item_data and item_data["name"]:
                data["name"] = item_data["name"]

            # Only set sequence if provided
            if "sequence" in item_data:
                try:
                    data["sequence"] = int(item_data["sequence"])
                except (ValueError, TypeError):
                    return None, "Invalid sequence. Must be a positive integer"

            return data, None

        # Validate all installments BEFORE creating any records
        validated_items = []
        for idx, item_data in enumerate(installments_data):
            if not isinstance(item_data, dict):
                errors.append(
                    {
                        "index": idx,
                        "error": "Each installment must be an object",
                        "data": item_data,
                    }
                )
                continue

            validated_data, error = validate_installment_data(item_data, idx)
            if error:
                errors.append({"index": idx, "error": error, "data": item_data})
                continue

            validated_items.append((idx, validated_data, item_data))

        # If there are any validation errors, do not create any records
        if errors:
            error_messages = [f"Index {err['index']}: {err['error']}" for err in errors]
            return Response(
                {
                    "detail": f"Validation failed. No installments were created. Errors: {'; '.join(error_messages)}",
                },
                status=400,
            )

        # All validations passed, now create all installments in a transaction using bulk_create
        # If ANY creation fails, the entire transaction will rollback automatically
        try:
            with transaction.atomic():
                # Auto-generate sequence for installments that don't have one
                # (bulk_create bypasses save() method, so we need to do this manually)
                from django.db.models import Max

                # Get max sequence for this academic year
                max_sequence = (
                    PaymentInstallment.objects.filter(
                        academic_year=academic_year
                    ).aggregate(max_seq=Max("sequence"))["max_seq"]
                    or 0
                )

                # Build list of PaymentInstallment objects and auto-generate sequence/name
                installment_objects = []
                current_sequence = max_sequence

                for idx, validated_data, item_data in validated_items:
                    # Auto-generate sequence if not provided
                    if (
                        "sequence" not in validated_data
                        or validated_data.get("sequence") is None
                    ):
                        current_sequence += 1
                        validated_data["sequence"] = current_sequence
                    else:
                        # If sequence is provided, ensure it's higher than max
                        if validated_data["sequence"] > current_sequence:
                            current_sequence = validated_data["sequence"]

                    # Auto-generate name if not provided
                    if "name" not in validated_data or not validated_data.get("name"):
                        validated_data["name"] = (
                            f"Installment {validated_data['sequence']}"
                        )

                    installment_objects.append(PaymentInstallment(**validated_data))

                # Use bulk_create for better performance (single query instead of N queries)
                # bulk_create returns objects with IDs populated (Django 2.2+)
                created_installments = PaymentInstallment.objects.bulk_create(
                    installment_objects
                )

        except Exception as e:
            # Transaction will automatically rollback on exception
            return Response(
                {
                    "detail": f"Error creating installments: {str(e)}. No records were inserted.",
                },
                status=400,
            )

        # All installments created successfully (transaction completed)
        # Clear cache for this academic year
        created_ids = [inst.id for inst in created_installments]
        clear_installment_cache(
            academic_year_id=academic_year.id,
            installment_ids=created_ids,
        )

        # IMPORTANT: bulk_create bypasses Django's save() method, so signals don't fire
        # Manually trigger payment summary recalculation for this academic year
        sync_payment_summaries_after_installment_change(academic_year.id)

        # Re-fetch with select_related for serializer
        created_installments_list = list(
            PaymentInstallment.objects.filter(id__in=created_ids)
            .select_related("academic_year")
            .order_by("sequence")
        )

        # Pre-calculate cumulative percentages
        cumulative_map = {}
        cumulative = 0.0
        for inst in created_installments_list:
            if inst.sequence is not None and inst.active:
                cumulative += float(inst.value)
                cumulative_map[inst.id] = cumulative

        serializer = PaymentInstallmentSerializer(
            created_installments_list,
            many=True,
            context={"cumulative_percentages": cumulative_map},
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def put(self, request, academic_year_id=None):
        """
        Update payment installment(s) in bulk for a specific academic year.

        Bulk: [{"id": "uuid1", "value": 50, "due_date": "2025-10-01", ...}, ...]
        """
        req_data = request.data

        # Support both single object and bulk (list or object with "installments" key)
        if isinstance(req_data, list):
            installments_data = req_data
        elif isinstance(req_data, dict) and "installments" in req_data:
            installments_data = req_data["installments"]
        else:
            installments_data = [req_data]

        # Get academic year
        academic_year = AcademicYear.get_academic_year(academic_year_id)
        if not academic_year:
            return Response(
                {"detail": "Academic year not found"},
                status=400,
            )

        # Clear cache BEFORE validation
        clear_installment_cache(academic_year_id=academic_year.id)

        # Validate individual installment data
        validated_items, error_response = validate_installments_data(
            installments_data,
            academic_year,
            existing_installments_dict={}  # Marker for update mode
        )
        if error_response:
            return error_response

        # Get IDs of installments being updated
        update_ids = {str(item[1].get("id")) for item in validated_items if "id" in item[1]}

        # Fetch existing installments
        existing_dict = {
            str(inst.id): inst
            for inst in PaymentInstallment.objects.filter(
                id__in=update_ids
            ).select_related("academic_year")
        }

        # Validate all IDs exist
        missing_ids = update_ids - set(existing_dict.keys())
        if missing_ids:
            return Response(
                {"detail": f"Installments not found: {', '.join(missing_ids)}"},
                status=404,
            )

        # Validate no overlapping dates
        error = validate_dates_no_overlap(installments_data, academic_year, exclude_ids=update_ids)
        if error:
            return error

        # Validate total equals 100%
        error = validate_total_percentage(installments_data, academic_year, exclude_ids=update_ids)
        if error:
            return error

        # All validations passed, update installments
        try:
            with transaction.atomic():
                for item_data in installments_data:
                    if not isinstance(item_data, dict) or "id" not in item_data:
                        continue

                    inst_id = str(item_data["id"])
                    inst = existing_dict[inst_id]

                    # Update fields
                    for field in ["name", "description", "value", "due_date", "sequence", "active"]:
                        if field in item_data:
                            if field == "value":
                                setattr(inst, field, float(item_data[field]))
                            elif field == "due_date":
                                setattr(inst, field, datetime.strptime(item_data[field], "%Y-%m-%d").date())
                            elif field == "sequence":
                                setattr(inst, field, int(item_data[field]))
                            elif field == "active":
                                setattr(inst, field, bool(item_data[field]))
                            else:
                                setattr(inst, field, item_data[field])

                    inst.save()
        except Exception as e:
            return Response(
                {"detail": f"Error updating installments: {str(e)}"},
                status=400,
            )

        # Clear cache after update
        clear_installment_cache(academic_year_id=academic_year.id)

        # Trigger payment summary recalculation
        sync_payment_summaries_after_installment_change(academic_year.id)

        # Return updated installments
        updated_list = list(
            PaymentInstallment.objects.filter(id__in=list(existing_dict.keys()))
            .select_related("academic_year")
            .order_by("sequence")
        )

        # Pre-calculate cumulative percentages
        all_ay_installments = list(
            PaymentInstallment.objects.filter(academic_year=academic_year, active=True)
            .order_by("sequence")
        )

        cumulative_map = {}
        cumulative = 0.0
        for inst in all_ay_installments:
            if inst.sequence is not None:
                cumulative += float(inst.value)
                cumulative_map[inst.id] = cumulative

        serializer = PaymentInstallmentSerializer(
            updated_list,
            many=True,
            context={"cumulative_percentages": cumulative_map},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


    # def put(self, request, academic_year_id):
    #     """
    #     Update payment installment(s) in bulk for a specific academic year.

    #     Bulk: [{"id": "uuid1", "name": "...", "value": 50, ...}, {"id": "uuid2", ...}]
    #     or {"installments": [{"id": "uuid1", ...}, ...]}
    #     """
    #     req_data = request.data

    #     # Validate academic_year exists
    #     cache_key = ACADEMIC_YEAR_CACHE_KEY.format(academic_year_id=academic_year_id)
    #     academic_year = cache.get(cache_key)

    #     if academic_year is None:
    #         try:
    #             academic_year = AcademicYear.objects.get(id=academic_year_id)
    #             cache.set(cache_key, academic_year, ACADEMIC_YEAR_CACHE_TIMEOUT)
    #         except AcademicYear.DoesNotExist:
    #             return Response(
    #                 {"detail": "Academic year not found"},
    #                 status=400,
    #             )

    #     # Clear installment cache BEFORE validation to ensure fresh data
    #     clear_installment_cache(academic_year_id=academic_year_id)

    #     # Support both single object and bulk (list or object with "installments" key)
    #     if isinstance(req_data, list):
    #         installments_data = req_data
    #     elif isinstance(req_data, dict) and "installments" in req_data:
    #         installments_data = req_data["installments"]
    #     else:
    #         # Single installment update
    #         installments_data = [req_data]

    #     if not installments_data:
    #         return Response(
    #             {"detail": "No installments provided"},
    #             status=400,
    #         )

    #     updated_installments = []
    #     errors = []

    #     # Get all installments to update and validate they exist
    #     installment_ids = []
    #     for item in installments_data:
    #         if isinstance(item, dict) and "id" in item:
    #             installment_ids.append(item["id"])

    #     if not installment_ids:
    #         return Response(
    #             {"detail": "Each installment must have an 'id' field"},
    #             status=400,
    #         )

    #     # Fetch all installments at once
    #     installments_dict = {
    #         str(inst.id): inst
    #         for inst in PaymentInstallment.objects.filter(
    #             id__in=installment_ids, academic_year_id=academic_year_id
    #         ).select_related("academic_year")
    #     }

    #     # Check if all installments exist
    #     missing_ids = [id for id in installment_ids if str(id) not in installments_dict]
    #     if missing_ids:
    #         return Response(
    #             {
    #                 "detail": f"Installments not found: {', '.join(map(str, missing_ids))}"
    #             },
    #             status=404,
    #         )

    #     # Cache academic year dates
    #     academic_year_start = academic_year.start_date
    #     academic_year_end = academic_year.end_date

    #     # Initialize parsed_due_dates dict for caching
    #     parsed_due_dates = {}

    #     # Validate that percentages sum to 100% (for bulk operations with value updates)
    #     if len(installments_data) > 1:
    #         # Build a map of updated values for calculation
    #         updated_values_map = {}
    #         for item in installments_data:
    #             if isinstance(item, dict) and "id" in item:
    #                 inst_id = str(item.get("id"))
    #                 if "value" in item:
    #                     updated_values_map[inst_id] = float(item.get("value", 0))
    #                 else:
    #                     # Use existing value if not being updated
    #                     if inst_id in installments_dict:
    #                         updated_values_map[inst_id] = float(
    #                             installments_dict[inst_id].value
    #                         )

    #         # Calculate total for ALL active installments: updated ones + other unchanged ones
    #         all_active = PaymentInstallment.objects.filter(
    #             academic_year=academic_year, active=True
    #         )
            
    #         total = 0.0
    #         for inst in all_active:
    #             inst_id = str(inst.id)
    #             if inst_id in updated_values_map:
    #                 # Use updated value
    #                 total += updated_values_map[inst_id]
    #             else:
    #                 # Keep existing value
    #                 total += float(inst.value)

    #         if abs(total - 100.0) > 0.01:
    #             return Response(
    #                 {
    #                     "detail": f"Total percentage of all installments must equal 100%. Current total: {total}%"
    #                 },
    #                 status=400,
    #             )

    #         # Validate that all due dates are unique
    #         existing_due_dates = set(
    #             PaymentInstallment.objects.filter(
    #                 academic_year=academic_year, active=True
    #             )
    #             .exclude(id__in=installment_ids)
    #             .values_list("due_date", flat=True)
    #         )

    #         due_dates_set = set(existing_due_dates)

    #         # Pre-parse due dates once
    #         for idx, item in enumerate(installments_data):
    #             if isinstance(item, dict) and "due_date" in item:
    #                 try:
    #                     due_date = datetime.strptime(
    #                         item["due_date"], "%Y-%m-%d"
    #                     ).date()
    #                     if due_date in due_dates_set:
    #                         return Response(
    #                             {
    #                                 "detail": f"Duplicate due date '{due_date}'. Each installment must have a unique due date (at least one day apart)."
    #                             },
    #                             status=400,
    #                         )
    #                     due_dates_set.add(due_date)
    #                     parsed_due_dates[idx] = due_date
    #                 except (ValueError, TypeError):
    #                     pass
    #             elif isinstance(item, dict) and "id" in item:
    #                 # Use existing due date if not being updated
    #                 inst_id = str(item.get("id"))
    #                 if inst_id in installments_dict:
    #                     existing_due_date = installments_dict[inst_id].due_date
    #                     if existing_due_date in due_dates_set:
    #                         return Response(
    #                             {
    #                                 "detail": f"Duplicate due date '{existing_due_date}'. Each installment must have a unique due date (at least one day apart)."
    #                             },
    #                             status=400,
    #                         )
    #                     due_dates_set.add(existing_due_date)

    #     def validate_installment_update(item_data, installment, index=None):
    #         """Validate a single installment update data"""
    #         errors_list = []

    #         # Validate value if being updated
    #         if "value" in item_data:
    #             try:
    #                 value = float(item_data.get("value", 0))
    #                 if value < 0 or value > 100:
    #                     errors_list.append("Percentage value must be between 0 and 100")
    #             except (ValueError, TypeError):
    #                 errors_list.append(
    #                     "Invalid value. Must be a number between 0 and 100"
    #                 )

    #         # Validate due_date if being updated
    #         if "due_date" in item_data:
    #             if index in parsed_due_dates:
    #                 due_date = parsed_due_dates[index]
    #             else:
    #                 try:
    #                     due_date = datetime.strptime(
    #                         item_data["due_date"], "%Y-%m-%d"
    #                     ).date()
    #                 except (ValueError, KeyError):
    #                     errors_list.append("Invalid due_date format. Use YYYY-MM-DD")
    #                     return None, errors_list

    #             # Validate due_date is within academic year
    #             if due_date < academic_year_start:
    #                 errors_list.append(
    #                     f"Due date ({due_date}) cannot be before academic year start date ({academic_year_start})"
    #                 )

    #             if due_date > academic_year_end:
    #                 errors_list.append(
    #                     f"Due date ({due_date}) cannot be after academic year end date ({academic_year_end})"
    #                 )

    #         # Validate sequence if being updated
    #         if "sequence" in item_data:
    #             try:
    #                 sequence = int(item_data["sequence"])
    #                 if sequence < 0:
    #                     errors_list.append("Sequence must be a positive integer")
    #             except (ValueError, TypeError):
    #                 errors_list.append("Invalid sequence. Must be a positive integer")

    #         if errors_list:
    #             return None, errors_list

    #         # Build update data dict
    #         update_data = {}
    #         update_fields = [
    #             "name",
    #             "description",
    #             "value",
    #             "due_date",
    #             "sequence",
    #             "active",
    #         ]

    #         for field in update_fields:
    #             if field in item_data:
    #                 if field == "value":
    #                     update_data[field] = float(item_data[field])
    #                 elif field == "due_date":
    #                     # Use cached parsed date if available
    #                     if index in parsed_due_dates:
    #                         update_data[field] = parsed_due_dates[index]
    #                     else:
    #                         update_data[field] = datetime.strptime(
    #                             item_data[field], "%Y-%m-%d"
    #                         ).date()
    #                 elif field == "sequence":
    #                     update_data[field] = int(item_data[field])
    #                 elif field == "active":
    #                     update_data[field] = bool(item_data[field])
    #                 else:
    #                     update_data[field] = item_data[field]

    #         return update_data, None

    #     # Validate all installments BEFORE updating any records
    #     validated_items = []
    #     for idx, item_data in enumerate(installments_data):
    #         if not isinstance(item_data, dict):
    #             errors.append(
    #                 {
    #                     "index": idx,
    #                     "error": "Each installment must be an object",
    #                     "data": item_data,
    #                 }
    #             )
    #             continue

    #         if "id" not in item_data:
    #             errors.append(
    #                 {
    #                     "index": idx,
    #                     "error": "Each installment must have an 'id' field",
    #                     "data": item_data,
    #                 }
    #             )
    #             continue

    #         inst_id = str(item_data["id"])
    #         if inst_id not in installments_dict:
    #             errors.append(
    #                 {
    #                     "index": idx,
    #                     "error": f"Installment with id '{inst_id}' not found",
    #                     "data": item_data,
    #                 }
    #             )
    #             continue

    #         installment = installments_dict[inst_id]
    #         validated_data, validation_errors = validate_installment_update(
    #             item_data, installment, idx
    #         )

    #         if validation_errors:
    #             errors.append(
    #                 {
    #                     "index": idx,
    #                     "id": inst_id,
    #                     "error": "; ".join(validation_errors),
    #                     "data": item_data,
    #                 }
    #             )
    #             continue

    #         validated_items.append((idx, installment, validated_data, item_data))

    #     # If there are any validation errors, do not update any records
    #     if errors:
    #         error_messages = [f"Index {err['index']}: {err['error']}" for err in errors]
    #         return Response(
    #             {
    #                 "detail": f"Validation failed. No installments were updated. Errors: {'; '.join(error_messages)}",
    #             },
    #             status=400,
    #         )

    #     # All validations passed, now update all installments in a transaction
    #     try:
    #         with transaction.atomic():
    #             # Collect installments to update and their fields
    #             installments_to_update = []
    #             update_fields_set = set()

    #             for idx, installment, validated_data, item_data in validated_items:
    #                 if validated_data:
    #                     # Update fields on the object
    #                     for field, value in validated_data.items():
    #                         setattr(installment, field, value)
    #                         update_fields_set.add(field)
    #                     installments_to_update.append(installment)

    #             # Use bulk_update for better performance
    #             if installments_to_update and update_fields_set:
    #                 PaymentInstallment.objects.bulk_update(
    #                     installments_to_update, list(update_fields_set), batch_size=100
    #                 )

    #     except Exception as e:
    #         # Transaction will automatically rollback on exception
    #         return Response(
    #             {
    #                 "detail": f"Error updating installments: {str(e)}. No records were updated.",
    #             },
    #             status=400,
    #         )

    #     # All installments updated successfully
    #     # Clear cache for this academic year
    #     updated_ids = [item[1].id for item in validated_items]
    #     clear_installment_cache(
    #         academic_year_id=academic_year.id,
    #         installment_ids=updated_ids,
    #     )

    #     # Manually trigger payment summary recalculation
    #     sync_payment_summaries_after_installment_change(academic_year.id)

    #     # Re-fetch with select_related for serializer
    #     updated_installments_list = list(
    #         PaymentInstallment.objects.filter(id__in=updated_ids)
    #         .select_related("academic_year")
    #         .order_by("sequence")
    #     )

    #     # Get all installments for this academic year to calculate cumulative correctly
    #     all_ay_installments = list(
    #         PaymentInstallment.objects.filter(academic_year=academic_year, active=True)
    #         .select_related("academic_year")
    #         .order_by("sequence")
    #     )

    #     # Pre-calculate cumulative percentages
    #     cumulative_map = {}
    #     cumulative = 0.0
    #     for inst in all_ay_installments:
    #         if inst.sequence is not None:
    #             cumulative += float(inst.value)
    #             cumulative_map[inst.id] = cumulative

    #     serializer = PaymentInstallmentSerializer(
    #         updated_installments_list,
    #         many=True,
    #         context={"cumulative_percentages": cumulative_map},
    #     )
    #     return Response(serializer.data)


class PaymentInstallmentDetailView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to retrieve, update or delete a specific payment installment.
    """

    def get_object(self, pk):
        try:
            return PaymentInstallment.objects.select_related(
                "academic_year"
            ).get(pk=pk)
        except PaymentInstallment.DoesNotExist:
            raise NotFound("Payment installment not found with this id")

    def get(self, request, pk):
        """Get a specific payment installment with caching"""
        # Try to get from cache first (same pattern as permission cache)
        cache_key = INSTALLMENT_DETAIL_CACHE_KEY.format(installment_id=pk)
        cached_data = cache.get(cache_key)

        if cached_data is not None:
            logger.debug(f"Cache HIT for installment detail: {cache_key}")
            return Response(cached_data)
        else:
            logger.debug(f"Cache MISS for installment detail: {cache_key}")

        # Not in cache, fetch from database
        installment = self.get_object(pk)

        # Pre-calculate cumulative percentage for this installment
        cumulative_map = {}
        if installment.sequence is not None and installment.active:
            # Get all active installments up to and including this one
            all_active_installments = list(
                PaymentInstallment.objects.filter(
                    academic_year=installment.academic_year,
                    active=True,
                    sequence__lte=installment.sequence,
                )
                .select_related("academic_year")
                .order_by("sequence")
            )

            cumulative = 0.0
            for inst in all_active_installments:
                if inst.sequence is not None:
                    cumulative += float(inst.value)
                    if inst.id == installment.id:
                        cumulative_map[inst.id] = cumulative

        serializer = PaymentInstallmentDetailSerializer(
            installment, context={"cumulative_percentages": cumulative_map}
        )
        response_data = serializer.data

        # Cache the full response for 24 hours (installments rarely change)
        # Cache is invalidated on create/update/delete operations (same pattern as permission cache)
        cache.set(cache_key, response_data, INSTALLMENT_CACHE_TIMEOUT)
        logger.debug(f"Cache SET for installment detail: {cache_key}")

        return Response(response_data)

    # def put(self, request, pk):
    #     """
    #     Update payment installment(s). Supports both single and bulk updates.

    #     Single: {"name": "...", "value": 50, "due_date": "2025-10-01", ...}
    #     Bulk: [{"id": "uuid1", "name": "...", "value": 50, ...}, {"id": "uuid2", ...}]
    #     or {"installments": [{"id": "uuid1", ...}, ...]}
    #     """
    #     req_data = request.data

    #     # Support both single object and bulk (list or object with "installments" key)
    #     if isinstance(req_data, list):
    #         installments_data = req_data
    #     elif isinstance(req_data, dict) and "installments" in req_data:
    #         installments_data = req_data["installments"]
    #     else:
    #         # Single installment update (use pk from URL)
    #         installments_data = [{**req_data, "id": pk}]

    #     if not installments_data:
    #         return Response(
    #             {"detail": "No installments provided"},
    #             status=400,
    #         )

    #     updated_installments = []
    #     errors = []

    #     # Get all installments to update and validate they exist
    #     installment_ids = []
    #     for item in installments_data:
    #         if isinstance(item, dict) and "id" in item:
    #             installment_ids.append(item["id"])

    #     if not installment_ids:
    #         return Response(
    #             {"detail": "Each installment must have an 'id' field"},
    #             status=400,
    #         )

    #     # Fetch all installments at once
    #     installments_dict = {
    #         str(inst.id): inst
    #         for inst in PaymentInstallment.objects.filter(
    #             id__in=installment_ids
    #         ).select_related("academic_year")
    #     }

    #     # Check if all installments exist
    #     missing_ids = [id for id in installment_ids if str(id) not in installments_dict]
    #     if missing_ids:
    #         return Response(
    #             {
    #                 "detail": f"Installments not found: {', '.join(map(str, missing_ids))}"
    #             },
    #             status=404,
    #         )

    #     # Get academic year from first installment (all should be in same academic year for bulk)
    #     first_installment = list(installments_dict.values())[0]
    #     academic_year = first_installment.academic_year

    #     # Validate that all installments belong to the same academic year
    #     for inst in installments_dict.values():
    #         if inst.academic_year != academic_year:
    #             return Response(
    #                 {
    #                     "detail": "All installments must belong to the same academic year"
    #                 },
    #                 status=400,
    #             )

    #     # Clear installment cache BEFORE validation to ensure fresh data
    #     clear_installment_cache(academic_year_id=academic_year.id)

    #     # Cache academic year dates
    #     academic_year_start = academic_year.start_date
    #     academic_year_end = academic_year.end_date

    #     # Initialize parsed_due_dates dict for caching (used in validation function)
    #     parsed_due_dates = {}

    #     # Validate that percentages sum to 100% (for bulk operations with value updates)
    #     if len(installments_data) > 1:
    #         # Build a map of updated values for calculation
    #         updated_values_map = {}
    #         for item in installments_data:
    #             if isinstance(item, dict) and "id" in item:
    #                 inst_id = str(item.get("id"))
    #                 if "value" in item:
    #                     updated_values_map[inst_id] = float(item.get("value", 0))
    #                 else:
    #                     # Use existing value if not being updated
    #                     if inst_id in installments_dict:
    #                         updated_values_map[inst_id] = float(
    #                             installments_dict[inst_id].value
    #                         )

    #         # Calculate total for ALL active installments: updated ones + other unchanged ones
    #         all_active = PaymentInstallment.objects.filter(
    #             academic_year=academic_year, active=True
    #         )
            
    #         total = 0.0
    #         for inst in all_active:
    #             inst_id = str(inst.id)
    #             if inst_id in updated_values_map:
    #                 # Use updated value
    #                 total += updated_values_map[inst_id]
    #             else:
    #                 # Keep existing value
    #                 total += float(inst.value)

    #         if abs(total - 100.0) > 0.01:
    #             return Response(
    #                 {
    #                     "detail": f"Total percentage of all installments must equal 100%. Current total: {total}%"
    #                 },
    #                 status=400,
    #             )

    #         # OPTIMIZATION: Fetch only due_dates in a single query instead of all installments
    #         existing_due_dates = set(
    #             PaymentInstallment.objects.filter(
    #                 academic_year=academic_year, active=True
    #             )
    #             .exclude(id__in=installment_ids)
    #             .values_list("due_date", flat=True)
    #         )

    #         # Validate that all due dates are unique (at least one day apart)
    #         due_dates_set = set(existing_due_dates)

    #         # Pre-parse due dates once (cache for use in validation function)
    #         for idx, item in enumerate(installments_data):
    #             if isinstance(item, dict) and "due_date" in item:
    #                 try:
    #                     due_date = datetime.strptime(
    #                         item["due_date"], "%Y-%m-%d"
    #                     ).date()
    #                     if due_date in due_dates_set:
    #                         return Response(
    #                             {
    #                                 "detail": f"Duplicate due date '{due_date}'. Each installment must have a unique due date (at least one day apart)."
    #                             },
    #                             status=400,
    #                         )
    #                     due_dates_set.add(due_date)
    #                     parsed_due_dates[idx] = due_date
    #                 except (ValueError, TypeError):
    #                     pass  # Will be caught in individual validation
    #             elif isinstance(item, dict) and "id" in item:
    #                 # Use existing due date if not being updated
    #                 inst_id = str(item.get("id"))
    #                 if inst_id in installments_dict:
    #                     existing_due_date = installments_dict[inst_id].due_date
    #                     if existing_due_date in due_dates_set:
    #                         return Response(
    #                             {
    #                                 "detail": f"Duplicate due date '{existing_due_date}'. Each installment must have a unique due date (at least one day apart)."
    #                             },
    #                             status=400,
    #                         )
    #                     due_dates_set.add(existing_due_date)

    #     def validate_installment_update(item_data, installment, index=None):
    #         """Validate a single installment update data"""
    #         errors_list = []

    #         # Validate value if being updated
    #         if "value" in item_data:
    #             try:
    #                 value = float(item_data.get("value", 0))
    #                 if value < 0 or value > 100:
    #                     errors_list.append("Percentage value must be between 0 and 100")
    #             except (ValueError, TypeError):
    #                 errors_list.append(
    #                     "Invalid value. Must be a number between 0 and 100"
    #                 )

    #         # Validate due_date if being updated - use cached parsed date if available
    #         if "due_date" in item_data:
    #             if index in parsed_due_dates:
    #                 due_date = parsed_due_dates[index]
    #             else:
    #                 try:
    #                     due_date = datetime.strptime(
    #                         item_data["due_date"], "%Y-%m-%d"
    #                     ).date()
    #                 except (ValueError, KeyError):
    #                     errors_list.append("Invalid due_date format. Use YYYY-MM-DD")
    #                     return None, errors_list

    #             # Validate due_date is within academic year (use cached dates)
    #             if due_date < academic_year_start:
    #                 errors_list.append(
    #                     f"Due date ({due_date}) cannot be before academic year start date ({academic_year_start})"
    #                 )

    #             if due_date > academic_year_end:
    #                 errors_list.append(
    #                     f"Due date ({due_date}) cannot be after academic year end date ({academic_year_end})"
    #                 )

    #         # Validate sequence if being updated
    #         if "sequence" in item_data:
    #             try:
    #                 sequence = int(item_data["sequence"])
    #                 if sequence < 0:
    #                     errors_list.append("Sequence must be a positive integer")
    #             except (ValueError, TypeError):
    #                 errors_list.append("Invalid sequence. Must be a positive integer")

    #         if errors_list:
    #             return None, errors_list

    #         # Build update data dict
    #         update_data = {}
    #         update_fields = [
    #             "name",
    #             "description",
    #             "value",
    #             "due_date",
    #             "sequence",
    #             "active",
    #         ]

    #         for field in update_fields:
    #             if field in item_data:
    #                 if field == "value":
    #                     update_data[field] = float(item_data[field])
    #                 elif field == "due_date":
    #                     # Use cached parsed date if available
    #                     if index in parsed_due_dates:
    #                         update_data[field] = parsed_due_dates[index]
    #                     else:
    #                         update_data[field] = datetime.strptime(
    #                             item_data[field], "%Y-%m-%d"
    #                         ).date()
    #                 elif field == "sequence":
    #                     update_data[field] = int(item_data[field])
    #                 elif field == "active":
    #                     update_data[field] = bool(item_data[field])
    #                 else:
    #                     update_data[field] = item_data[field]

    #         return update_data, None

    #     # Validate all installments BEFORE updating any records
    #     validated_items = []
    #     for idx, item_data in enumerate(installments_data):
    #         if not isinstance(item_data, dict):
    #             errors.append(
    #                 {
    #                     "index": idx,
    #                     "error": "Each installment must be an object",
    #                     "data": item_data,
    #                 }
    #             )
    #             continue

    #         if "id" not in item_data:
    #             errors.append(
    #                 {
    #                     "index": idx,
    #                     "error": "Each installment must have an 'id' field",
    #                     "data": item_data,
    #                 }
    #             )
    #             continue

    #         inst_id = str(item_data["id"])
    #         if inst_id not in installments_dict:
    #             errors.append(
    #                 {
    #                     "index": idx,
    #                     "error": f"Installment with id '{inst_id}' not found",
    #                     "data": item_data,
    #                 }
    #             )
    #             continue

    #         installment = installments_dict[inst_id]
    #         validated_data, validation_errors = validate_installment_update(
    #             item_data, installment, idx
    #         )

    #         if validation_errors:
    #             errors.append(
    #                 {
    #                     "index": idx,
    #                     "id": inst_id,
    #                     "error": "; ".join(validation_errors),
    #                     "data": item_data,
    #                 }
    #             )
    #             continue

    #         validated_items.append((idx, installment, validated_data, item_data))

    #     # If there are any validation errors, do not update any records
    #     if errors:
    #         error_messages = [f"Index {err['index']}: {err['error']}" for err in errors]
    #         return Response(
    #             {
    #                 "detail": f"Validation failed. No installments were updated. Errors: {'; '.join(error_messages)}",
    #             },
    #             status=400,
    #         )

    #     # All validations passed, now update all installments in a transaction using bulk_update
    #     # If ANY update fails, the entire transaction will rollback automatically
    #     try:
    #         with transaction.atomic():
    #             # Collect installments to update and their fields
    #             installments_to_update = []
    #             update_fields_set = set()

    #             for idx, installment, validated_data, item_data in validated_items:
    #                 if validated_data:
    #                     # Update fields on the object
    #                     for field, value in validated_data.items():
    #                         setattr(installment, field, value)
    #                         update_fields_set.add(field)
    #                     installments_to_update.append(installment)

    #             # Use bulk_update for better performance (fewer queries)
    #             if installments_to_update and update_fields_set:
    #                 PaymentInstallment.objects.bulk_update(
    #                     installments_to_update, list(update_fields_set), batch_size=100
    #                 )

    #     except Exception as e:
    #         # Transaction will automatically rollback on exception
    #         return Response(
    #             {
    #                 "detail": f"Error updating installments: {str(e)}. No records were updated.",
    #             },
    #             status=400,
    #         )

    #     # All installments updated successfully (transaction completed)
    #     # Clear cache for this academic year
    #     updated_ids = [item[1].id for item in validated_items]
    #     clear_installment_cache(
    #         academic_year_id=academic_year.id,
    #         installment_ids=updated_ids,
    #     )

    #     # IMPORTANT: bulk_update bypasses Django's save() method, so signals don't fire
    #     # Manually trigger payment summary recalculation for this academic year
    #     sync_payment_summaries_after_installment_change(academic_year.id)

    #     # Re-fetch with select_related for serializer
    #     updated_ids = [item[1].id for item in validated_items]
    #     updated_installments_list = list(
    #         PaymentInstallment.objects.filter(id__in=updated_ids)
    #         .select_related("academic_year")
    #         .order_by("sequence")
    #     )

    #     # Get all installments for this academic year to calculate cumulative correctly
    #     all_ay_installments = list(
    #         PaymentInstallment.objects.filter(academic_year=academic_year, active=True)
    #         .select_related("academic_year")
    #         .order_by("sequence")
    #     )

    #     # Pre-calculate cumulative percentages for all installments in academic year
    #     cumulative_map = {}
    #     cumulative = 0.0
    #     for inst in all_ay_installments:
    #         if inst.sequence is not None:
    #             cumulative += float(inst.value)
    #             cumulative_map[inst.id] = cumulative

    #     serializer = PaymentInstallmentSerializer(
    #         updated_installments_list,
    #         many=True,
    #         context={"cumulative_percentages": cumulative_map},
    #     )
    #     return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        """Delete a specific payment installment"""
        installment = self.get_object(pk)

        # Store IDs for cache clearing
        academic_year_id = installment.academic_year.id

        # OPTIMIZATION: Use count() instead of exists() if we only need to check existence
        # Check if there are any student payment schedules using this installment
        if (
            hasattr(installment, "student_schedules")
            and installment.student_schedules.count() > 0
        ):
            return Response(
                {
                    "detail": "Cannot delete installment that has student payment schedules. "
                    "Please remove or update student schedules first."
                },
                status=400,
            )

        installment_id = installment.id
        installment.delete()

        # Clear cache after deletion
        clear_installment_cache(
            academic_year_id=academic_year_id,
            installment_ids=[installment_id],
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

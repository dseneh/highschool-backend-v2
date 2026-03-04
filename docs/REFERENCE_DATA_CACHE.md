# Reference Data Caching System

## Overview

The Reference Data Caching System provides high-performance caching for frequently accessed data that rarely changes. This includes grade levels, sections, academic years, subjects, payment methods, and more.

## Features

- ✅ **Automatic Cache Invalidation** - Cache is automatically cleared when data changes
- ✅ **Tenant-Aware** - All caching is scoped per school
- ✅ **24-Hour Cache Lifetime** - Configurable timeout for cached data
- ✅ **Signal-Based Updates** - Django signals ensure cache stays synchronized
- ✅ **Comprehensive API** - RESTful endpoints for accessing cached data
- ✅ **Force Refresh** - Option to bypass cache when needed

## Cached Data Types

The following reference data is cached:

1. **Grade Levels** - All grade levels for a school
2. **Sections** - Class sections (optionally filtered by academic year)
3. **Academic Years** - All academic years including current year
4. **Semesters** - Semester periods (optionally filtered by academic year)
5. **Marking Periods** - Grading periods within semesters
6. **Subjects** - All subjects taught at the school
7. **Payment Methods** - Available payment methods
8. **Transaction Types** - Income and expense transaction types
9. **Installments** - Payment installment schedules

## Architecture

```
┌─────────────────┐
│   API Request   │
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│  Cache Service      │
│  (cache_service.py) │
└────────┬────────────┘
         │
    ┌────┴────┐
    │  Cache  │ No → Database Query
    │  Hit?   │        │
    └────┬────┘        │
         │ Yes         │
         ▼             ▼
    Return Data   Return Data
                   + Cache It
```

### Auto-Invalidation Flow

```
Model Save/Delete
     ↓
Django Signal Triggered
     ↓
Signal Handler (cache_signals.py)
     ↓
ReferenceDataCache.invalidate_*()
     ↓
Cache Key Deleted
     ↓
Next Request Fetches Fresh Data
```

## Usage

### 1. Python/Django Code

```python
from common.cache_service import ReferenceDataCache

# Get all grade levels for a school
grade_levels = ReferenceDataCache.get_grade_levels(school_id)

# Get sections filtered by academic year
sections = ReferenceDataCache.get_sections(
    school_id, 
    academic_year_id='some-uuid'
)

# Get current academic year
current_year = ReferenceDataCache.get_current_academic_year(school_id)

# Get all reference data at once (useful for dashboard initialization)
all_data = ReferenceDataCache.get_all_reference_data(
    school_id,
    academic_year_id='optional-uuid'
)

# Force refresh (bypass cache)
fresh_data = ReferenceDataCache.get_subjects(
    school_id, 
    force_refresh=True
)

# Manual cache invalidation (usually not needed - signals handle this)
ReferenceDataCache.invalidate_grade_levels(school_id)
ReferenceDataCache.invalidate_all_for_school(school_id)
```

### 2. REST API Endpoints

#### Get All Reference Data
```http
GET /api/v1/schools/{school_id}/reference-data/
```

Query parameters:
- `academic_year_id` (optional) - Filter by academic year
- `force_refresh` (optional) - Set to `true` to bypass cache
- `include_hidden` (optional) - Include hidden transaction types

Response:
```json
{
  "grade_levels": [...],
  "sections": [...],
  "academic_years": [...],
  "current_academic_year": {...},
  "semesters": [...],
  "marking_periods": [...],
  "subjects": [...],
  "payment_methods": [...],
  "transaction_types": [...],
  "installments": [...]
}
```

#### Get Specific Data Types

```http
GET /api/v1/schools/{school_id}/reference-data/grade-levels/
GET /api/v1/schools/{school_id}/reference-data/sections/?academic_year_id={id}
GET /api/v1/schools/{school_id}/reference-data/academic-years/
GET /api/v1/schools/{school_id}/reference-data/current-academic-year/
```

#### Manually Invalidate Cache

```http
POST /api/v1/schools/{school_id}/cache/invalidate/
Content-Type: application/json

{
  "data_type": "all"
}
```

Valid `data_type` values:
- `all` - Invalidate everything
- `grade_levels`
- `sections`
- `academic_years`
- `semesters`
- `marking_periods`
- `subjects`
- `payment_methods`
- `transaction_types`
- `installments`

### 3. Frontend/UI Usage

```typescript
// Get all reference data for initialization
const response = await fetch(
  `/api/v1/schools/${schoolId}/reference-data/`
);
const referenceData = await response.json();

// Store in your state management (Redux, Zustand, Context, etc.)
const {
  grade_levels,
  sections,
  current_academic_year,
  subjects,
  payment_methods,
} = referenceData;

// Use in dropdowns, filters, etc.
<Select>
  {grade_levels.map(level => (
    <option key={level.id} value={level.id}>
      {level.name}
    </option>
  ))}
</Select>
```

## Configuration

Cache timeout can be configured in `api/settings/cache.py`:

```python
# Default is 24 hours (86400 seconds)
REFERENCE_DATA_CACHE_TIMEOUT = 86400
```

## Automatic Cache Invalidation

Cache is automatically invalidated when models change via Django signals defined in `common/cache_signals.py`.

### Signal Handlers

Each model has a signal handler that triggers cache invalidation:

```python
@receiver([post_save, post_delete], sender='core.GradeLevel')
def invalidate_grade_level_cache(sender, instance, **kwargs):
    school_id = str(instance.school_id)
    ReferenceDataCache.invalidate_grade_levels(school_id)
```

### Cascade Invalidation

Some changes trigger cascade invalidation:

- **Academic Year** changes → Also invalidates sections, semesters, installments
- **Semester** changes → Also invalidates marking periods
- **School** deletion → Invalidates ALL reference data for that school

## Performance Benefits

### Before Caching
```
Each dashboard load:
- 10 database queries for reference data
- ~150ms query time
- Multiplied by every user request
```

### After Caching
```
First request:
- 10 database queries + cache storage
- ~150ms query time

Subsequent requests (cache hit):
- 0 database queries
- ~2-5ms retrieval time from cache
- 30-50x faster! 🚀
```

## Cache Keys Format

Cache keys follow this pattern:
```
ref_data:{school_id}:{data_type}:{optional_suffix}
```

Examples:
```
ref_data:123e4567-e89b-12d3-a456-426614174000:grade_levels
ref_data:123e4567-e89b-12d3-a456-426614174000:sections:all
ref_data:123e4567-e89b-12d3-a456-426614174000:sections:ay_abc123
ref_data:123e4567-e89b-12d3-a456-426614174000:current_academic_year
```

## Best Practices

1. **Always use the cache service** - Don't query reference data directly
2. **Use `force_refresh=True` sparingly** - Only when you absolutely need fresh data
3. **Let signals handle invalidation** - Don't manually invalidate unless debugging
4. **Fetch all at once for dashboards** - Use `get_all_reference_data()` for initial load
5. **Filter appropriately** - Pass `academic_year_id` when relevant to reduce data size

## Monitoring

Check cache performance in logs:
```
Cache HIT: grade_levels for school 123...
Cache MISS: sections for school 123..., ay=abc...
Invalidated cache: academic_years for school 123...
```

## Troubleshooting

### Cache not invalidating
1. Check that signals are connected (verify in `common/apps.py`)
2. Ensure `ready()` method is called on app startup
3. Check logs for signal errors

### Stale data showing
1. Manually invalidate: `POST /api/v1/schools/{id}/cache/invalidate/`
2. Check cache backend is working (Redis or DB cache)
3. Verify timeout settings

### Performance issues
1. Ensure cache backend (Redis) is properly configured
2. Check if `force_refresh=True` is being overused
3. Monitor cache hit/miss ratios in logs

## Related Files

- `common/cache_service.py` - Main cache service class
- `common/cache_signals.py` - Signal handlers for auto-invalidation
- `common/views_cache.py` - REST API endpoints
- `common/urls.py` - URL routing
- `api/settings/cache.py` - Cache configuration

## Future Enhancements

Potential improvements:
- [ ] Cache warming on app startup
- [ ] Cache preloading for anticipated academic year changes
- [ ] Metrics/stats endpoint for cache performance
- [ ] Selective cache refresh (update without full invalidation)
- [ ] Background task to refresh stale cache before expiry

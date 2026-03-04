# Quick Reference: Cached Data Usage

## Import
```python
from common.cache_service import ReferenceDataCache
```

## Get Data (Python)

```python
# Grade Levels
grade_levels = ReferenceDataCache.get_grade_levels(school_id)

# Sections (all)
sections = ReferenceDataCache.get_sections(school_id)

# Sections (filtered by academic year)
sections = ReferenceDataCache.get_sections(school_id, academic_year_id)

# Academic Years
academic_years = ReferenceDataCache.get_academic_years(school_id)

# Current Academic Year
current_year = ReferenceDataCache.get_current_academic_year(school_id)

# Semesters
semesters = ReferenceDataCache.get_semesters(school_id)
semesters = ReferenceDataCache.get_semesters(school_id, academic_year_id)

# Marking Periods
marking_periods = ReferenceDataCache.get_marking_periods(school_id)
marking_periods = ReferenceDataCache.get_marking_periods(school_id, semester_id)

# Subjects
subjects = ReferenceDataCache.get_subjects(school_id)

# Payment Methods
payment_methods = ReferenceDataCache.get_payment_methods(school_id)

# Transaction Types
transaction_types = ReferenceDataCache.get_transaction_types(school_id)
transaction_types = ReferenceDataCache.get_transaction_types(school_id, include_hidden=True)

# Installments
installments = ReferenceDataCache.get_installments(school_id)
installments = ReferenceDataCache.get_installments(school_id, academic_year_id)

# All at once (for dashboard)
all_data = ReferenceDataCache.get_all_reference_data(school_id, academic_year_id)
```

## Force Refresh (Bypass Cache)
```python
# Add force_refresh=True to any method
fresh_data = ReferenceDataCache.get_grade_levels(school_id, force_refresh=True)
```

## API Endpoints

```bash
# Get all reference data
GET /api/v1/schools/{school_id}/reference-data/

# With filters
GET /api/v1/schools/{school_id}/reference-data/?academic_year_id={id}
GET /api/v1/schools/{school_id}/reference-data/?force_refresh=true

# Individual endpoints
GET /api/v1/schools/{school_id}/reference-data/grade-levels/
GET /api/v1/schools/{school_id}/reference-data/sections/
GET /api/v1/schools/{school_id}/reference-data/academic-years/
GET /api/v1/schools/{school_id}/reference-data/current-academic-year/

# Invalidate cache
POST /api/v1/schools/{school_id}/cache/invalidate/
Body: {"data_type": "all"}
```

## Frontend (JavaScript/TypeScript)

```typescript
// Fetch all at once
const response = await fetch(`/api/v1/schools/${schoolId}/reference-data/`);
const {
  grade_levels,
  sections,
  academic_years,
  current_academic_year,
  semesters,
  subjects,
  payment_methods,
  transaction_types,
  installments
} = await response.json();

// Store in state and use in dropdowns, filters, etc.
```

## Cache Keys
```
ref_data:{school_id}:grade_levels
ref_data:{school_id}:sections:all
ref_data:{school_id}:sections:ay_{academic_year_id}
ref_data:{school_id}:academic_years
ref_data:{school_id}:current_academic_year
ref_data:{school_id}:semesters:all
ref_data:{school_id}:marking_periods:all
ref_data:{school_id}:subjects
ref_data:{school_id}:payment_methods
ref_data:{school_id}:transaction_types:visible
ref_data:{school_id}:installments:all
```

## Automatic Invalidation

Cache is **automatically** invalidated when:
- GradeLevel saved/deleted → `invalidate_grade_levels()`
- Section saved/deleted → `invalidate_sections()`
- AcademicYear saved/deleted → `invalidate_academic_years()` + related
- Semester saved/deleted → `invalidate_semesters()` + marking_periods
- MarkingPeriod saved/deleted → `invalidate_marking_periods()`
- Subject saved/deleted → `invalidate_subjects()`
- PaymentMethod saved/deleted → `invalidate_payment_methods()`
- TransactionType saved/deleted → `invalidate_transaction_types()`
- PaymentInstallment saved/deleted → `invalidate_installments()`

**No manual action needed!** Django signals handle everything.

## Configuration

In `api/settings/cache.py`:
```python
REFERENCE_DATA_CACHE_TIMEOUT = 86400  # 24 hours
```

## When to Use

✅ **Use caching for:**
- Dashboard initialization
- Dropdown/select options
- Filter options
- Any repetitive reference data queries

❌ **Don't use caching for:**
- Transactional data (payments, grades, enrollments)
- User-specific data
- Frequently changing data
- Real-time data

## Performance

- Cache hit: **~2-5ms**
- Cache miss + DB query: **~100-200ms**
- Improvement: **30-50x faster**

## Docs

Full documentation: `/docs/REFERENCE_DATA_CACHE.md`

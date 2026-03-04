# Dashboard Summary API

## Overview

The Dashboard Summary API provides comprehensive, optimized statistics for school management dashboards. It leverages the cached reference data infrastructure for maximum performance and minimal database load.

## Endpoint

```
GET /api/v1/schools/{school_id}/dashboard/summary/
```

## Authentication

Requires authentication token in header:
```
Authorization: Bearer <token>
```

## Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `academic_year_id` | string | No | Filter statistics by specific academic year. Uses current academic year if not provided. |
| `force_refresh` | boolean | No | If `true`, bypasses cache for reference data. Default: `false` |

## Response Structure

```json
{
  "overview": {
    "total_students": 1250,
    "total_staff": 85,
    "total_divisions": 3,
    "total_grade_levels": 12,
    "total_sections": 45,
    "total_subjects": 28,
    "total_academic_years": 5,
    "current_academic_year": {
      "id": "uuid",
      "name": "2025-2026",
      "start_date": "2025-09-01",
      "end_date": "2026-06-30",
      "current": true,
      "status": "active"
    }
  },
  "students": {
    "total_active": 1250,
    "by_gender": {
      "Male": 650,
      "Female": 600
    },
    "by_grade_level": [
      {
        "current_grade_level__name": "Grade 9",
        "count": 120
      }
    ],
    "recent_enrollments_30_days": 15
  },
  "finance": {
    "total_billed": 1500000.00,
    "total_paid": 1350000.00,
    "outstanding_balance": 150000.00,
    "collection_rate": 90.00,
    "bills_by_status": {
      "paid": 800,
      "partial": 150,
      "unpaid": 100
    },
    "recent_transactions_7_days": {
      "count": 45,
      "total_amount": 125000.00
    },
    "income_vs_expense": {
      "income": 1400000.00,
      "expense": 350000.00,
      "net": 1050000.00
    }
  },
  "academic": {
    "total_grades_recorded": 15000,
    "average_grade": 82.5,
    "total_students_graded": 1200,
    "high_achievers": 180,
    "top_subjects": [
      {
        "subject__name": "Mathematics",
        "avg_grade": 85.5,
        "count": 1200
      }
    ]
  },
  "recent_activity": {
    "recent_payments": [
      {
        "id": "uuid",
        "amount": 5000.00,
        "payment_date": "2026-01-17",
        "student__first_name": "John",
        "student__last_name": "Doe",
        "payment_method__name": "Bank Transfer"
      }
    ],
    "recent_enrollments": [
      {
        "id": "uuid",
        "first_name": "Jane",
        "last_name": "Smith",
        "student_id": "STU-2026-001",
        "created_at": "2026-01-15T10:30:00Z"
      }
    ],
    "recent_transactions": [
      {
        "id": "uuid",
        "amount": 2500.00,
        "transaction_date": "2026-01-17",
        "description": "Salary payment",
        "transaction_type__name": "Staff Salary",
        "transaction_type__type": "expense"
      }
    ]
  },
  "metadata": {
    "school_id": "uuid",
    "school_name": "Liberia Duja High School",
    "academic_year_id": "uuid",
    "generated_at": "2026-01-17T14:30:00Z"
  }
}
```

## Example Usage

### Get Current Year Summary

```bash
curl -X GET "https://api.example.com/api/v1/schools/dujar/dashboard/summary/" \
  -H "Authorization: Bearer <token>"
```

### Get Specific Academic Year Summary

```bash
curl -X GET "https://api.example.com/api/v1/schools/dujar/dashboard/summary/?academic_year_id=abc123" \
  -H "Authorization: Bearer <token>"
```

### Force Fresh Data

```bash
curl -X GET "https://api.example.com/api/v1/schools/dujar/dashboard/summary/?force_refresh=true" \
  -H "Authorization: Bearer <token>"
```

## Performance Characteristics

### Optimizations

1. **Cached Reference Data**: Uses `ReferenceDataCache` for divisions, grade levels, sections, subjects, and academic years
2. **Selective Queries**: Only queries necessary data with proper filtering
3. **Aggregation**: Uses database aggregations (COUNT, SUM, AVG) for statistics
4. **Limited Results**: Recent activity queries are limited to last 5 items

### Expected Response Times

- **Cold Cache** (first request): ~200-400ms
- **Warm Cache** (subsequent requests): ~100-150ms
- **With force_refresh=true**: ~250-450ms

### Database Queries

Typical dashboard summary makes approximately:
- **8-10 database queries** for statistics
- **0 queries** for cached reference data (after first load)

## Data Sections

### 1. Overview Stats
General school metrics using cached reference data plus real-time student/staff counts.

### 2. Student Stats
- Active student count
- Gender distribution
- Grade level distribution
- Recent enrollments (last 30 days)

### 3. Finance Stats
- Total billed vs paid amounts
- Outstanding balance
- Collection rate percentage
- Bills by status breakdown
- Recent transactions (last 7 days)
- Income vs expense analysis

### 4. Academic Stats
- Total grades recorded
- Average grade across all subjects
- Number of high achievers (grade >= 90)
- Top performing subjects

### 5. Recent Activity
- Last 5 payments
- Last 5 student enrollments
- Last 5 transactions

## Frontend Integration Example

```typescript
// React/Next.js example
import { useEffect, useState } from 'react';

interface DashboardSummary {
  overview: any;
  students: any;
  finance: any;
  academic: any;
  recent_activity: any;
  metadata: any;
}

export function useDashboardSummary(schoolId: string) {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchSummary() {
      try {
        setLoading(true);
        const response = await fetch(
          `/api/v1/schools/${schoolId}/dashboard/summary/`,
          {
            headers: {
              'Authorization': `Bearer ${getToken()}`,
            },
          }
        );
        
        if (!response.ok) throw new Error('Failed to fetch dashboard');
        
        const summary = await response.json();
        setData(summary);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }

    fetchSummary();
  }, [schoolId]);

  return { data, loading, error };
}
```

## Error Responses

### 401 Unauthorized
```json
{
  "detail": "Authentication credentials were not provided."
}
```

### 404 Not Found
```json
{
  "detail": "School does not exist with this id"
}
```

### 500 Internal Server Error
```json
{
  "error": "Failed to fetch dashboard summary",
  "detail": "Error message details"
}
```

## Customization

The dashboard summary can be extended by modifying the helper functions in `common/views_dashboard.py`:

- `_get_overview_stats()` - Add more general statistics
- `_get_student_stats()` - Add student-specific metrics
- `_get_finance_stats()` - Add financial KPIs
- `_get_academic_stats()` - Add academic performance metrics
- `_get_recent_activity()` - Add more activity types

## Best Practices

1. **Cache Duration**: Dashboard data is most accurate when reference data cache is fresh (24-hour timeout)
2. **Academic Year**: Always specify academic_year_id for year-specific reports
3. **Polling**: Refresh dashboard every 30-60 seconds in active dashboards
4. **Force Refresh**: Only use when absolutely necessary to get latest reference data
5. **Error Handling**: Always handle potential null values in response

## Related Endpoints

- **Reference Data**: `/api/v1/schools/{id}/reference-data/`
- **Cache Invalidation**: `/api/v1/schools/{id}/cache/invalidate/`
- **Current Academic Year**: `/api/v1/schools/{id}/academic-years/current/`

## Notes

- All amounts are in the school's configured currency
- Dates are in ISO 8601 format
- Statistics are calculated in real-time except cached reference data
- Academic stats depend on grading system implementation

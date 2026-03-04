# Student Bill Summary API

This API provides comprehensive bill summary views for students across different organizational levels within a school for a selected academic year.

## Endpoint

```
GET /api/students/schools/{school_id}/bill-summary/
```

## Features

- **Flexible Grouping**: View bill summaries by grade level, section, or individual students
- **Optimized Performance**: Uses efficient database queries with aggregations and annotations
- **Pagination Support**: Handles large datasets with configurable pagination
- **Search Functionality**: Search across names and identifiers at each level
- **Comprehensive Data**: Includes total bills, payments, balances, and averages
- **Academic Year Filtering**: Filter data for specific academic years

## Query Parameters

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `academic_year_id` | string | Academic year ID or "current" for current academic year |
| `view_type` | string | One of: `grade_level`, `section`, `student` |

### Conditional Parameters

| Parameter | Type | Required When | Description |
|-----------|------|---------------|-------------|
| `grade_level_id` | string | `view_type` is "section" or "student" | Grade level ID |
| `section_id` | string | `view_type` is "student" | Section ID |

### Optional Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `search` | string | Search term for filtering results |
| `page` | integer | Page number for pagination |
| `page_size` | integer | Number of results per page (max 200) |

## Usage Examples

### 1. Grade Level Summary

Get bill summary grouped by all grade levels in a school:

```bash
GET /api/students/schools/abc123/bill-summary/?academic_year_id=current&view_type=grade_level
```

**Response:**
```json
{
  "count": 12,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "grade123",
      "name": "1st Grade",
      "short_name": "G1",
      "level": 1,
      "student_count": 45,
      "total_bills": "67500.00",
      "total_paid": "45000.00",
      "balance": "22500.00",
      "avg_bill_per_student": "1500.00"
    }
    // ... more grade levels
  ],
  "academic_year": {
    "id": "year123",
    "name": "2024-2025",
    "current": true
  },
  "school_summary": {
    "total_students": 540,
    "total_bills": "810000.00",
    "total_paid": "567000.00"
  },
  "view_type": "grade_level"
}
```

### 2. Section Summary

Get bill summary for all sections within a specific grade level:

```bash
GET /api/students/schools/abc123/bill-summary/?academic_year_id=current&view_type=section&grade_level_id=grade123
```

**Response:**
```json
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "section123",
      "name": "1st Grade A",
      "grade_level": {
        "id": "grade123",
        "name": "1st Grade",
        "level": 1
      },
      "student_count": 15,
      "total_bills": "22500.00",
      "total_paid": "15000.00",
      "balance": "7500.00",
      "avg_bill_per_student": "1500.00"
    }
    // ... more sections
  ],
  "academic_year": {
    "id": "year123",
    "name": "2024-2025",
    "current": true
  },
  "grade_level": {
    "id": "grade123",
    "name": "1st Grade",
    "level": 1
  },
  "grade_level_summary": {
    "total_students": 45,
    "total_bills": "67500.00",
    "total_paid": "45000.00"
  },
  "view_type": "section"
}
```

### 3. Student Summary

Get bill summary for all students within a specific section:

```bash
GET /api/students/schools/abc123/bill-summary/?academic_year_id=current&view_type=student&section_id=section123
```

**Response:**
```json
{
  "count": 15,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "student123",
      "id_number": "2024001",
      "first_name": "John",
      "last_name": "Doe",
      "full_name": "John Doe",
      "enrollment_info": {
        "id": "enroll123",
        "status": "active",
        "date_enrolled": "2024-09-01",
        "enrolled_as": "new"
      },
      "total_bills": "1500.00",
      "total_paid": "1000.00",
      "balance": "500.00",
      "detailed_billing": {
        "tuition_fees": "1200.00",
        "other_fees": "300.00",
        "approved_payments": "1000.00",
        "pending_payments": "0.00",
        "projected_balance": "500.00"
      }
    }
    // ... more students
  ],
  "academic_year": {
    "id": "year123",
    "name": "2024-2025",
    "current": true
  },
  "section": {
    "id": "section123",
    "name": "1st Grade A",
    "grade_level": {
      "id": "grade123",
      "name": "1st Grade",
      "level": 1
    }
  },
  "section_summary": {
    "total_students": 15,
    "total_bills": "22500.00",
    "total_paid": "15000.00"
  },
  "view_type": "student"
}
```

### 4. Search Functionality

Search for specific grade levels, sections, or students:

```bash
# Search grade levels
GET /api/students/schools/abc123/bill-summary/?academic_year_id=current&view_type=grade_level&search=grade

# Search sections
GET /api/students/schools/abc123/bill-summary/?academic_year_id=current&view_type=section&grade_level_id=grade123&search=A

# Search students
GET /api/students/schools/abc123/bill-summary/?academic_year_id=current&view_type=student&section_id=section123&search=john
```

## Data Fields Explained

### Common Fields

- **total_bills**: Sum of all bill amounts for the entity
- **total_paid**: Sum of all approved payments (income transactions)
- **balance**: Calculated as `total_bills - total_paid`
- **student_count**: Number of students in the entity

### Grade Level Specific

- **level**: Numerical level of the grade (1, 2, 3, etc.)
- **avg_bill_per_student**: Average bill amount per student

### Student Specific

- **detailed_billing**: Breakdown of tuition vs other fees and payment status
- **enrollment_info**: Current enrollment details for the academic year
- **projected_balance**: Balance considering pending payments

## Performance Optimizations

1. **Database Annotations**: Uses Django's `annotate()` with aggregation functions
2. **Conditional Aggregation**: Uses `Case/When` for efficient conditional sums
3. **Selective Queries**: Only fetches necessary fields and relationships
4. **Pagination**: Limits memory usage for large datasets
5. **Index Usage**: Leverages database indexes on foreign keys and dates

## Error Handling

The API returns appropriate HTTP status codes:

- **200**: Success
- **400**: Bad Request (missing/invalid parameters)
- **404**: Not Found (school, academic year, grade level, or section not found)
- **403**: Forbidden (insufficient permissions)
- **500**: Internal Server Error

## Permissions

Requires `BILLING_READ` permission to access the bill summary data.

## Implementation Notes

### Database Efficiency

The implementation uses Django ORM's advanced features for optimal database performance:

```python
# Efficient aggregation with conditional logic
.annotate(
    total_paid=Sum(
        Case(
            When(
                transactions__status='approved',
                transactions__type__type='income',
                then='transactions__amount'
            ),
            default=0,
            output_field=DecimalField(max_digits=15, decimal_places=2)
        )
    )
)
```

### Memory Management

- Uses pagination to avoid loading large datasets into memory
- Selective field loading with `select_related()` and `prefetch_related()`
- Aggregation at the database level rather than in Python

### Extensibility

The design allows for easy extension:

- Additional grouping levels (e.g., by division)
- More detailed payment breakdowns
- Additional filtering options
- Custom date ranges

## Integration Examples

### Frontend Integration

```javascript
// Fetch grade level summary
const response = await fetch('/api/students/schools/school123/bill-summary/?academic_year_id=current&view_type=grade_level');
const data = await response.json();

// Display in a table or chart
data.results.forEach(gradeLevel => {
    console.log(`${gradeLevel.name}: ${gradeLevel.student_count} students, Balance: $${gradeLevel.balance}`);
});
```

### Drill-down Navigation

```javascript
async function loadSummary(viewType, params) {
    const url = new URL('/api/students/schools/school123/bill-summary/');
    url.searchParams.set('view_type', viewType);
    url.searchParams.set('academic_year_id', 'current');
    
    Object.entries(params).forEach(([key, value]) => {
        if (value) url.searchParams.set(key, value);
    });
    
    const response = await fetch(url);
    return await response.json();
}

// Navigate from grade level -> section -> student
const gradeLevels = await loadSummary('grade_level', {});
const sections = await loadSummary('section', { grade_level_id: 'selected_grade' });
const students = await loadSummary('student', { section_id: 'selected_section' });
```

This API provides a comprehensive and efficient way to view student billing information at different organizational levels, making it easy to identify payment patterns and outstanding balances across the school.
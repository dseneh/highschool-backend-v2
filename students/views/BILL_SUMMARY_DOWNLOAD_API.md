# Student Bill Summary Download API

## Overview
Download student billing summaries as CSV or Excel files with optional filtering by academic year, grade level, section, and enrollment status.

## Endpoint
```
GET /api/students/schools/{school_id}/bill-summary/download/
```

## Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `academic_year_id` | string | No | Academic year ID or "current" for current year. Defaults to "current" |
| `grade_level_id` | UUID | No | Filter by specific grade level |
| `section_id` | UUID | No | Filter by specific section |
| `enrolled_as` | string | No | Filter by enrollment type (e.g., "boarder", "day_student") |
| `status` | string | No | Filter by enrollment status (e.g., "active", "inactive") |
| `format` | string | No | Output format: "csv" or "excel". Defaults to "csv" |

## Response
Returns a downloadable file (CSV or Excel) with the following columns:

- **Student ID**: Student's ID number (id_number) or system ID
- **Student Name**: Student's full name (first name + last name)
- **Grade Level**: Student's grade level
- **Section**: Student's section/class
- **En. As**: Enrollment type (Boarder, Day Student, etc.)
- **Tuition**: Total tuition fees charged
- **Others**: Total other fees (non-tuition) charged
- **Total Bills**: Total amount billed to the student (Tuition + Others)
- **Total Paid**: Total amount paid by the student
- **Balance**: Remaining balance (Total Bills - Total Paid)
- **Percent Paid (%)**: Percentage of bills that have been paid

## File Format

### CSV Format
- Plain text file with comma-separated values
- Includes header information (school name, academic year, generation timestamp)
- Summary totals at the bottom

### Excel Format
- XLSX file with formatted cells
- Styled header row with blue background
- Number formatting for currency values
- Auto-adjusted column widths
- Summary totals with bold formatting

## Example Requests

### Download all students (CSV)
```http
GET /api/students/schools/123/bill-summary/download/
```

### Download current year students (Excel)
```http
GET /api/students/schools/123/bill-summary/download/?academic_year_id=current&format=excel
```

### Download specific grade level
```http
GET /api/students/schools/123/bill-summary/download/?grade_level_id=456
```

### Download specific section
```http
GET /api/students/schools/123/bill-summary/download/?section_id=789
```

### Download only boarders
```http
GET /api/students/schools/123/bill-summary/download/?enrolled_as=boarder
```

### Download active students only
```http
GET /api/students/schools/123/bill-summary/download/?status=active
```

### Complex filter: Active boarders in Grade 10
```http
GET /api/students/schools/123/bill-summary/download/?grade_level_id=456&enrolled_as=boarder&status=active&format=excel
```

## File Naming Convention
Files are automatically named using the pattern:
```
student_billing_summary_{academic_year_name}_{timestamp}.{extension}
```

Example: `student_billing_summary_2025-2026_20251019_143022.csv`

## Permissions
Requires `Student.BILLING_READ` permission.

## Error Responses

### 400 Bad Request
- Invalid format parameter
```json
{
  "detail": "format must be either 'csv' or 'excel'"
}
```

### 404 Not Found
- Academic year not found
```json
{
  "detail": "Academic year not found or no current academic year set"
}
```

- Grade level not found
```json
{
  "detail": "Grade level not found"
}
```

- Section not found
```json
{
  "detail": "Section not found"
}
```

### 501 Not Implemented
- Excel export attempted without openpyxl library installed
```json
{
  "detail": "Excel export requires openpyxl library to be installed"
}
```

### 500 Internal Server Error
- Unexpected error during file generation
```json
{
  "detail": "Error generating download: {error message}"
}
```

## Notes

1. **Performance**: Large datasets may take time to generate. Consider using filters to limit the result set.

2. **Excel Support**: Excel format requires the `openpyxl` library to be installed. If not available, use CSV format instead.

3. **Currency Symbol**: The currency symbol is automatically fetched from the school's default currency settings.

4. **Data Accuracy**: 
   - Total Bills are calculated from all bills for the academic year
   - Total Paid includes only approved income transactions
   - Balance is calculated as: Total Bills - Total Paid

5. **Enrollment Data**: Students must have an active enrollment in the specified academic year to appear in the report.

## Related Endpoints

- `GET /api/students/schools/{school_id}/bill-summary/` - View paginated bill summary in JSON format
- `GET /api/students/schools/{school_id}/bill-summary/metadata/` - Get metadata for filtering options
- `GET /api/students/schools/{school_id}/bill-summary/quick-stats/` - Get quick statistics

## Installation Requirements

For Excel export functionality:
```bash
pip install openpyxl
```

Or add to `requirements.txt`:
```
openpyxl>=3.0.0
```

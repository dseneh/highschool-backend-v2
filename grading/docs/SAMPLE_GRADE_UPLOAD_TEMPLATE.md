# Sample Grade Upload Template

This document describes the Excel template format for bulk grade uploads.

## Template Structure

The Excel file should contain the following columns in this order:

### Required Columns (First 6 columns)

1. **id_number** - Student's ID number (must match existing student)
   - **Important**: Format as TEXT in Excel to preserve leading zeros (e.g., '0121774)
   - If your IDs have leading zeros, prefix with a single quote in Excel: `'0121774`
   - Or format the entire column as "Text" before entering data
2. **student_name** - Student's full name (for verification/readability)
3. **grade_level** - Grade level name (e.g., "Grade 9", "Grade 10")
4. **section** - Section name (e.g., "Section A", "9A")
5. **subject** - Subject name (e.g., "Mathematics", "English Language")
6. **academic_year** - Academic year name (e.g., "2024-2025")
7. **marking_period** - Marking period name (e.g., "Marking Period 1", "Quarter 1")

### Assessment Columns (Dynamic - Based on Generated Assessments)

After the required columns, add one column for each assessment in the section/academic year.
The column name MUST exactly match the assessment name in the system.

**Column Format**: `<assessment_name>`
**Value Format**: Numeric score (e.g., 85, 92.5)

## Sample Excel Template

```
| id_number | student_name      | grade_level | section    | academic_year | marking_period      | Quiz 1 | Assignment 1 | Participation | Attendance | Test 1 | Final Grade |
|-------------------|-------------------|-------------|------------|---------------|---------------------|--------|--------------|---------------|------------|--------|-------------|
| S001              | John Doe          | Grade 9     | Section A  | 2024-2025     | Marking Period 1    | 28     | 18           | 5             | 5          | 35     | 85          |
| S002              | Jane Smith        | Grade 9     | Section A  | 2024-2025     | Marking Period 1    | 25     | 20           | 5             | 4          | 38     | 92          |
| S003              | Bob Johnson       | Grade 9     | Section A  | 2024-2025     | Marking Period 1    | 30     | 19           | 4             | 5          | 36     | 88          |
| S004              | Alice Williams    | Grade 9     | Section A  | 2024-2025     | Marking Period 1    | 27     | 17           | 5             | 5          | 32     | 80          |
```

## Example for Multiple Marking Periods

If uploading grades for multiple marking periods, include all rows:

```
| id_number | student_name      | grade_level | section    | academic_year | marking_period      | Quiz 1 | Test 1 | Final Grade |
|-------------------|-------------------|-------------|------------|---------------|---------------------|--------|--------|-------------|
| S001              | John Doe          | Grade 9     | Section A  | 2024-2025     | Marking Period 1    | 28     | 35     | 85          |
| S001              | John Doe          | Grade 9     | Section A  | 2024-2025     | Marking Period 2    | 26     | 33     | 82          |
| S001              | John Doe          | Grade 9     | Section A  | 2024-2025     | Marking Period 3    | 29     | 38     | 90          |
| S002              | Jane Smith        | Grade 9     | Section A  | 2024-2025     | Marking Period 1    | 25     | 38     | 92          |
| S002              | Jane Smith        | Grade 9     | Section A  | 2024-2025     | Marking Period 2    | 27     | 36     | 88          |
```

## Important Notes

### Student ID Numbers with Leading Zeros
**⚠️ IMPORTANT**: If your student IDs have leading zeros (e.g., 0121774, 0001234), you MUST format the column as TEXT in Excel:

**Option 1: Format Column as Text** (Recommended)
1. Select the `id_number` column
2. Right-click → Format Cells
3. Select "Text" from the Category list
4. Click OK
5. Enter your student IDs (they will be stored as text)

**Option 2: Prefix with Single Quote**
- Enter student IDs with a leading single quote: `'0121774`
- Excel will treat it as text and preserve the leading zeros
- The quote won't be included in the uploaded data

**Why This Matters**: 
- Excel automatically converts `0121774` to `121774` (removes leading zeros)
- The upload system now preserves leading zeros when reading
- But you still need to format properly in Excel to avoid data loss when creating the file

### Assessment Names Must Match
- Assessment column names must **exactly** match the assessment names in the database
- Names are case-sensitive
- Include spaces and special characters exactly as they appear in the system

### Scoring Rules
- Scores must be numeric (can include decimals: 85.5)
- Scores cannot be negative
- Scores cannot exceed the assessment's max_score
- Empty cells will be skipped (grade not created/updated)

### Student Identification
- Students are matched by `id_number`
- The `student_name` column is for verification/readability only
- If a student is not found, that row will be skipped with an error

### Marking Period Matching
- Marking periods are matched by name
- Must exist in the specified academic year
- If filtering by marking period (query parameter), only matching rows will be processed

## API Usage

### Endpoint
```
POST /api/grading/sections/<section_id>/grades/upload/
```

### Query Parameters
- `academic_year` (required): Academic year ID
- `subject_id` (required): Subject ID for validation (ensures all grades are for this subject)
- `marking_period` (optional): Marking period ID for filtering
- `override_grades` (optional, default=false): If true, updates grades regardless of status; if false, only updates grades with 'draft' or null status

### Request
- Content-Type: `multipart/form-data`
- File parameter: `file`
- Supported formats: `.xlsx`, `.xls`

### Example Request (curl)
```bash
# Default behavior (only updates draft grades)
curl -X POST \
  "http://localhost:8000/api/grading/sections/abc123/grades/upload/?academic_year=xyz789&subject_id=subj456" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@grades_upload.xlsx"

# Force override all grades regardless of status
curl -X POST \
  "http://localhost:8000/api/grading/sections/abc123/grades/upload/?academic_year=xyz789&subject_id=subj456&override_grades=true" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@grades_upload.xlsx"
```

### Example Request (JavaScript/Fetch)
```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);

// Default behavior (only updates draft grades)
const response = await fetch(
  `/api/grading/sections/${sectionId}/grades/upload/?academic_year=${academicYearId}&subject_id=${subjectId}`,
  {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`
    },
    body: formData
  }
);

// Force override all grades
const responseOverride = await fetch(
  `/api/grading/sections/${sectionId}/grades/upload/?academic_year=${academicYearId}&subject_id=${subjectId}&override_grades=true`,
  {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`
    },
    body: formData
  }
);

const result = await response.json();
console.log(result);
```

### Response Format
```json
{
  "detail": "Processed 25 students. Created 150 grades, updated 30 grades.",
  "statistics": {
    "total_rows": 25,
    "students_processed": 25,
    "grades_created": 150,
    "grades_updated": 30,
    "grades_skipped": 0,
    "error_count": 0
  },
  "errors": []
}
```

### Error Response Example
```json
{
  "detail": "Processed 23 students. Created 140 grades, updated 20 grades. 5 errors occurred.",
  "statistics": {
    "total_rows": 25,
    "students_processed": 23,
    "grades_created": 140,
    "grades_updated": 20,
    "grades_skipped": 0,
    "error_count": 5
  },
  "errors": [
    {
      "row": 5,
      "student_id": "S005",
      "error": "Student not found with ID: S005"
    },
    {
      "row": 12,
      "student_id": "S012",
      "assessment": "Quiz 1",
      "error": "Score 35 exceeds max score 30"
    }
  ]
}
```

## Best Practices

### 1. Generate Template from Frontend
The frontend should generate the template by:
1. Fetching section details
2. Fetching enrolled students
3. Fetching assessments for the section/academic year
4. Creating Excel with proper column headers
5. Pre-filling student information

### 2. Validation Before Upload
- Validate file format (.xlsx or .xls)
- Check file size (recommend max 5MB)
- Verify required columns exist
- Check for duplicate student rows

### 3. Error Handling
- Display errors clearly to users
- Allow partial success (process valid rows even if some fail)
- Show which specific rows/students had errors
- Allow users to download error report

### 4. Progress Feedback
- Show upload progress
- Display processing status
- Provide detailed results summary
- Allow users to review changes before finalizing

## Template Generation Example (Frontend)

```javascript
async function generateGradeUploadTemplate(sectionId, academicYearId, markingPeriodId) {
  // 1. Fetch section data
  const section = await fetchSection(sectionId);
  
  // 2. Fetch enrolled students
  const students = await fetchEnrolledStudents(sectionId, academicYearId);
  
  // 3. Fetch assessments
  const assessments = await fetchSectionAssessments(
    sectionId, 
    academicYearId, 
    markingPeriodId
  );
  
  // 4. Create Excel workbook
  const workbook = XLSX.utils.book_new();
  
  // 5. Build header row
  const headers = [
    'id_number',
    'student_name',
    'grade_level',
    'section',
    'academic_year',
    'marking_period',
    ...assessments.map(a => a.name)
  ];
  
  // 6. Build data rows
  const data = [headers];
  
  students.forEach(student => {
    const row = [
      student.id_number,
      student.full_name,
      section.grade_level.name,
      section.name,
      section.academic_year.name,
      markingPeriod.name,
      ...assessments.map(() => '') // Empty cells for grades
    ];
    data.push(row);
  });
  
  // 7. Create worksheet and add to workbook
  const worksheet = XLSX.utils.aoa_to_sheet(data);
  XLSX.utils.book_append_sheet(workbook, worksheet, 'Grades');
  
  // 8. Download file
  XLSX.writeFile(workbook, `grades_${section.name}_${markingPeriod.name}.xlsx`);
}
```

## Permissions Required

- `GRADEBOOK_GRADE_ENTRY` permission is required to upload grades
- Users must have access to the specific section and academic year

## Data Safety

- All operations are wrapped in a database transaction
- If any critical error occurs, all changes are rolled back
- Existing grades are updated (not duplicated)
- Grades are created with `DRAFT` status by default
- `created_by` and `updated_by` fields track the user who uploaded

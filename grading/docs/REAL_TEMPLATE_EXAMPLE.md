# Real Grade Upload Template Examples

Based on actual database data from Dujar High School.

## Example 1: Single Entry Mode (Current System)

**System Configuration**: Single Entry Mode  
**Academic Year**: 2025-2026  
**Section**: General (Nursery 1)  
**Subject**: Mathematics  
**Marking Period**: Marking Period 1  

### Excel Template

| id_number | student_name        | grade_level | section | academic_year | marking_period      | Final Grade |
|-------------------|---------------------|-------------|---------|---------------|---------------------|-------------|
| 0121774           | Michael Blair       | Nursery 1   | General | 2025-2026     | Marking Period 1    | 85          |
| 0121777           | Carlos Stewart      | Nursery 1   | General | 2025-2026     | Marking Period 1    | 92          |
| 0121776           | Cole Curry          | Nursery 1   | General | 2025-2026     | Marking Period 1    | 78          |
| 0121778           | Melissa Lester      | Nursery 1   | General | 2025-2026     | Marking Period 1    | 88          |
| 0121779           | Cameron Williams    | Nursery 1   | General | 2025-2026     | Marking Period 1    | 95          |
| 0121780           | Micheal Williams    | Nursery 1   | General | 2025-2026     | Marking Period 1    | 82          |
| 0121781           | Brian Diaz          | Nursery 1   | General | 2025-2026     | Marking Period 1    | 90          |

**Notes**:
- In single entry mode, there is only ONE assessment per marking period: "Final Grade"
- Max score for Final Grade: 100 points
- This is the simplest grading mode where teachers only enter one final grade per marking period

---

## Example 2: Multiple Entry Mode (Hypothetical with Template Data)

**System Configuration**: Multiple Entry Mode  
**Academic Year**: 2025-2026  
**Section**: Arts (Grade 9)  
**Subject**: English  
**Marking Period**: Marking Period 1  

### Excel Template (with standard assessment templates)

| id_number | student_name        | grade_level | section | academic_year | marking_period      | Quiz | Assignment | Participation | Attendance | Test |
|-------------------|---------------------|-------------|---------|---------------|---------------------|------|------------|---------------|------------|------|
| S2024001          | John Smith          | Grade 9     | Arts    | 2025-2026     | Marking Period 1    | 28   | 18         | 5             | 5          | 38   |
| S2024002          | Jane Doe            | Grade 9     | Arts    | 2025-2026     | Marking Period 1    | 25   | 20         | 5             | 4          | 35   |
| S2024003          | Robert Johnson      | Grade 9     | Arts    | 2025-2026     | Marking Period 1    | 30   | 19         | 4             | 5          | 36   |
| S2024004          | Maria Garcia        | Grade 9     | Arts    | 2025-2026     | Marking Period 1    | 27   | 17         | 5             | 5          | 32   |
| S2024005          | David Lee           | Grade 9     | Arts    | 2025-2026     | Marking Period 1    | 29   | 18         | 5             | 5          | 40   |
| S2024006          | Sarah Williams      | Grade 9     | Arts    | 2025-2026     | Marking Period 1    | 26   | 19         | 4             | 4          | 34   |
| S2024007          | Michael Brown       | Grade 9     | Arts    | 2025-2026     | Marking Period 1    | 24   | 16         | 5             | 5          | 31   |

**Assessment Details** (Multiple Entry Mode):
- **Quiz**: Max Score 30 points
- **Assignment**: Max Score 20 points  
- **Participation**: Max Score 5 points
- **Attendance**: Max Score 5 points
- **Test**: Max Score 40 points

**Total Possible**: 100 points per marking period

---

## Example 3: Multiple Marking Periods Upload

Upload grades for the same students across multiple marking periods in one file.

### Excel Template

| id_number | student_name   | grade_level | section | academic_year | marking_period      | Final Grade |
|-------------------|----------------|-------------|---------|---------------|---------------------|-------------|
| 0121774           | Michael Blair  | Nursery 1   | General | 2025-2026     | Marking Period 1    | 85          |
| 0121774           | Michael Blair  | Nursery 1   | General | 2025-2026     | Marking Period 2    | 88          |
| 0121774           | Michael Blair  | Nursery 1   | General | 2025-2026     | Marking Period 3    | 90          |
| 0121777           | Carlos Stewart | Nursery 1   | General | 2025-2026     | Marking Period 1    | 92          |
| 0121777           | Carlos Stewart | Nursery 1   | General | 2025-2026     | Marking Period 2    | 90          |
| 0121777           | Carlos Stewart | Nursery 1   | General | 2025-2026     | Marking Period 3    | 94          |
| 0121776           | Cole Curry     | Nursery 1   | General | 2025-2026     | Marking Period 1    | 78          |
| 0121776           | Cole Curry     | Nursery 1   | General | 2025-2026     | Marking Period 2    | 82          |
| 0121776           | Cole Curry     | Nursery 1   | General | 2025-2026     | Marking Period 3    | 85          |

**Notes**:
- Each student has multiple rows (one per marking period)
- This allows uploading an entire semester or year at once
- Filter by marking period using query parameter to upload specific periods only

---

## API Usage with Real Data

### Upload for Marking Period 1 Only

```bash
curl -X POST \
  "http://localhost:8000/api/grading/sections/3b2a344438764d3699db6e6f1ca5ad99/grades/upload/?academic_year=cef52bb88be7415a880098aee9d87a0b" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@nursery1_math_mp1_grades.xlsx"
```

### Upload All Marking Periods (No Filter)

```bash
curl -X POST \
  "http://localhost:8000/api/grading/sections/3b2a344438764d3699db6e6f1ca5ad99/grades/upload/?academic_year=cef52bb88be7415a880098aee9d87a0b" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@nursery1_math_all_grades.xlsx"
```

---

## Expected Results

### Success Response
```json
{
  "detail": "Processed 7 students. Created 7 grades, updated 0 grades.",
  "statistics": {
    "total_rows": 7,
    "students_processed": 7,
    "grades_created": 7,
    "grades_updated": 0,
    "grades_skipped": 0,
    "error_count": 0
  },
  "errors": []
}
```

### Response with Errors
```json
{
  "detail": "Processed 6 students. Created 6 grades, updated 0 grades. 1 errors occurred.",
  "statistics": {
    "total_rows": 7,
    "students_processed": 6,
    "grades_created": 6,
    "grades_updated": 0,
    "grades_skipped": 0,
    "error_count": 1
  },
  "errors": [
    {
      "row": 5,
      "student_id": "0121999",
      "error": "Student not found with ID: 0121999"
    }
  ]
}
```

---

## Important Validation Rules

Based on the real system:

1. **Assessment Names Must Match Exactly**
   - Current system: "Final Grade" (single entry)
   - Template system: "Quiz", "Assignment", "Participation", "Attendance", "Test"
   - Names are case-sensitive and must match database exactly

2. **Student ID Numbers**
   - Format: 7-digit numbers (e.g., 0121774)
   - Must exist in the database
   - Can use either student.id_number or student.id

3. **Score Validation**
   - Single entry "Final Grade": 0-100 points
   - Multiple entry assessments: Varies by type (see max_score)
   - Cannot be negative
   - Cannot exceed max_score

4. **Marking Period Names**
   - Must match exactly: "Marking Period 1", "Marking Period 2", etc.
   - Must belong to the specified academic year
   - Case-sensitive

---

## Frontend Template Generation Example

Based on real database structure:

```javascript
async function generateGradeTemplate(sectionId, academicYearId, markingPeriodId) {
  // Fetch data from API
  const section = await fetch(`/api/sections/${sectionId}`).then(r => r.json());
  const students = await fetch(
    `/api/sections/${sectionId}/students?academic_year=${academicYearId}`
  ).then(r => r.json());
  
  const assessments = await fetch(
    `/api/sections/${sectionId}/assessments?academic_year=${academicYearId}&marking_period=${markingPeriodId}`
  ).then(r => r.json());
  
  // Create Excel data
  const headers = [
    'id_number',
    'student_name', 
    'grade_level',
    'section',
    'academic_year',
    'marking_period',
    ...assessments.map(a => a.name) // e.g., ["Final Grade"] or ["Quiz", "Assignment", ...]
  ];
  
  const rows = students.map(student => [
    student.id_number,              // 0121774
    student.full_name,               // Michael Blair
    section.grade_level.name,        // Nursery 1
    section.name,                    // General
    section.academic_year.name,      // 2025-2026
    markingPeriod.name,              // Marking Period 1
    ...assessments.map(() => '')     // Empty cells for grade entry
  ]);
  
  // Generate Excel file
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet([headers, ...rows]);
  XLSX.utils.book_append_sheet(wb, ws, 'Grades');
  XLSX.writeFile(wb, `${section.name}_${markingPeriod.name}_template.xlsx`);
}
```

---

## Common Errors and Solutions

### Error: "Assessment not found: Quiz for Marking Period 1"
**Cause**: System is in single entry mode, only "Final Grade" exists  
**Solution**: Use only "Final Grade" column, or switch system to multiple entry mode

### Error: "Student not found with ID: 0121999"
**Cause**: Student doesn't exist or wrong ID  
**Solution**: Verify student ID number in the system, check for typos

### Error: "Score 105 exceeds max score 100"
**Cause**: Score higher than assessment's max_score  
**Solution**: Ensure all scores are ≤ max_score for that assessment

### Error: "Marking period not found: Quarter 1"
**Cause**: Marking period name doesn't match database  
**Solution**: Use exact name from database (e.g., "Marking Period 1")

### Error: "Multiple assessments found with name: Final Grade"
**Cause**: Multiple subjects/gradebooks with same assessment name  
**Solution**: System will use the gradebook for the specified section and subject

---

## Testing the Upload

1. **Download the sample template** from your frontend
2. **Fill in grades** for a few students
3. **Test with small batch** (2-3 students) first
4. **Review the response** for any errors
5. **Fix errors** and retry
6. **Upload complete file** once validated

This ensures data integrity and helps identify issues early!

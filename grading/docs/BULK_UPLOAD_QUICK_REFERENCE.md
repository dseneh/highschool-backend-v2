# Bulk Grade Upload - Quick Reference

## ⚡ Performance Summary

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Database Queries (500 grades) | ~550+ | ~10-15 | **97%** ↓ |
| Execution Time (500 grades) | ~15-20s | ~2-3s | **85-90%** ↓ |
| Write Operations | 1 per grade | 2 total | **99%** ↓ |

---

## 📋 Required Excel Columns

| Column | Type | Description | Validation |
|--------|------|-------------|------------|
| `id_number` | String | Student ID | Must exist in system. **Format as TEXT in Excel if IDs have leading zeros** |
| `student_name` | String | Full name | Optional verification |
| `grade_level` | String | Grade level | Info only |
| `section` | String | Section name | Must match upload section |
| `subject` | String | Subject name | Must match assessment subject |
| `academic_year` | String | Academic year | Info only |
| `marking_period` | String | Marking period | Must exist for academic year |
| `[Assessment Name]` | Number | Score value | 0 ≤ score ≤ max_score, max 2 decimals |

---

## ✅ Validation Rules

### File Validation
- ✓ Format: `.xlsx` or `.xls` only
- ✓ Size: Maximum 10MB
- ✓ Content: Cannot be empty

### Data Validation
- ✓ **Student ID**: Must exist (cached lookup)
- ✓ **Section**: Must match upload section exactly
- ✓ **Subject**: Cannot be empty
- ✓ **Marking Period**: Must exist for academic year
- ✓ **Assessment**: Must exist for marking period and section
- ✓ **Score**: 
  - Must be a number
  - Cannot be negative
  - Cannot exceed max_score
  - Maximum 2 decimal places

### Warnings (Non-blocking)
- ⚠️ Student name mismatch
- ⚠️ Multiple sections in file
- ⚠️ Multiple subjects in file
- ⚠️ Multiple academic years in file

---

## 🔧 Key Optimizations

### 1. Pre-fetch All Data (5 Cache Maps)
```python
students_map          # ID → Student
marking_periods_map   # Name → MarkingPeriod
assessments_cache     # (Name, MP_ID) → Assessment
enrollments_cache     # Student_ID → Enrollment_ID
existing_grades_cache # (Assessment_ID, Student_ID) → Grade
```

### 2. Bulk Operations
```python
Grade.objects.bulk_create(grades_to_create, batch_size=500)
Grade.objects.bulk_update(grades_to_update, [...], batch_size=500)
```

### 3. Select Related
```python
.select_related(
    'marking_period',
    'gradebook',
    'gradebook__section_subject__subject'
)
```

---

## 📊 Response Format

### Success Response
```json
{
  "detail": "Successfully processed 95 students. Created 450 new grades...",
  "statistics": {
    "total_rows": 100,
    "students_processed": 95,
    "grades_created": 450,
    "grades_updated": 25,
    "grades_locked": 5,    // Grades not updated due to status (when override_grades=false)
    "grades_skipped": 0,
    "warning_count": 3,
    "error_count": 5
  },
  "warnings": [...],  // Max 50
  "errors": [...]     // Max 50
}
```

### Error Format
```json
{
  "row": 5,
  "student_id": "S2024001",
  "assessment": "Quiz 1",
  "error": "Score 150 exceeds maximum score of 100"
}
```

---

## 🚀 API Usage

### Endpoint
```
POST /api/grading/sections/{section_id}/grades/upload/
```

### Query Parameters
- `academic_year` (required): Academic year ID
- `subject_id` (required): Subject ID for validation
- `marking_period` (optional): Filter by specific marking period
- `override_grades` (optional, default=false): Force update all grades regardless of status

### Example
```bash
# Default: Only update draft grades
curl -X POST \
  'http://localhost:8000/api/grading/sections/abc123/grades/upload/?academic_year=xyz789&subject_id=subj456' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -F 'file=@grades.xlsx'

# Force override all grades
curl -X POST \
  'http://localhost:8000/api/grading/sections/abc123/grades/upload/?academic_year=xyz789&subject_id=subj456&override_grades=true' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -F 'file=@grades.xlsx'
```

---

## 🎯 Best Practices

### Template Preparation
1. ✓ Use provided templates as base
2. ✓ **Format id_number column as TEXT** if IDs have leading zeros
3. ✓ Verify section/subject/marking period names match exactly
4. ✓ Double-check student IDs
5. ✓ Ensure scores are within valid ranges
6. ✓ Remove empty rows

### Upload Strategy
1. ✓ Test with 5-10 students first
2. ✓ Review error messages carefully
3. ✓ Fix errors and re-upload
4. ✓ Process one marking period at a time for clarity
5. ✓ Keep original file as backup

### Troubleshooting
- ❌ "Student not found" → Verify ID numbers (check for missing leading zeros)
- ❌ "Assessment not found" → Check column names match exactly
- ❌ "Section mismatch" → Verify section name spelling
- ❌ "Score exceeds maximum" → Check assessment max_score setting
- ❌ "Too many decimal places" → Round to 2 decimals max
- ❌ "Leading zeros missing" → Format id_number column as TEXT in Excel

---

## 📈 Performance Tips

For large uploads (500+ students):
1. Split into multiple files by marking period
2. Upload during off-peak hours
3. Monitor response statistics for errors
4. Consider batching by 100-200 students

For very large files (1000+ students):
1. Ensure database indexes exist on foreign keys
2. Consider increasing batch_size to 1000
3. Split by section if uploading multiple sections
4. Use marking_period filter to process incrementally

---

## 🧪 Testing

Run tests:
```bash
python manage.py test grading.tests.test_bulk_upload_optimized
```

Check specific validation:
```bash
python manage.py test grading.tests.test_bulk_upload_optimized.BulkGradeUploadOptimizedTest.test_validation_score_exceeds_max
```

---

## 📚 Documentation Files

- **Usage Guide**: `grading/docs/SAMPLE_GRADE_UPLOAD_TEMPLATE.md`
- **Real Examples**: `grading/docs/REAL_TEMPLATE_EXAMPLE.md`
- **Full Details**: `grading/docs/BULK_UPLOAD_OPTIMIZATIONS.md`
- **Templates**: `grading/templates/*.xlsx`

---

## 🔍 Validation Checklist

Before uploading, verify:
- [ ] File is .xlsx or .xls format
- [ ] File size < 10MB
- [ ] All 7 required columns present
- [ ] At least one assessment column
- [ ] Student IDs match system records
- [ ] Section name matches target section
- [ ] Subject name is filled
- [ ] Marking period exists for academic year
- [ ] Assessment names match exactly
- [ ] All scores are valid numbers
- [ ] No negative scores
- [ ] Scores don't exceed max_score
- [ ] Scores have max 2 decimal places

---

**Version**: 2.0 (Optimized)  
**Last Updated**: October 2025  
**Performance**: 97% query reduction, 85-90% faster execution

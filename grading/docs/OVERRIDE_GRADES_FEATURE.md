# Override Grades Feature

## Overview
The `override_grades` parameter provides control over which existing grades can be updated during bulk upload based on their status.

---

## Parameter Details

### Query Parameter
- **Name**: `override_grades`
- **Type**: Boolean (string: 'true' or 'false')
- **Required**: No
- **Default**: `false`
- **Values**:
  - `false` (default): Only updates grades with status `DRAFT` or `null`
  - `true`: Updates grades regardless of current status

---

## Behavior

### Default Behavior (override_grades=false)

When `override_grades` is `false` or not provided, the system protects grades that have progressed through the workflow:

**Updatable Statuses**:
- ✅ `DRAFT` - Grade is in draft state
- ✅ `null` - Grade has no status set

**Protected Statuses** (cannot be updated):
- 🔒 `PENDING` - Grade submitted for review
- 🔒 `REVIEWED` - Grade has been reviewed
- 🔒 `SUBMITTED` - Grade officially submitted
- 🔒 `APPROVED` - Grade has been approved
- 🔒 `REJECTED` - Grade was rejected

**What Happens**:
- Protected grades are **skipped**
- Counter: `grades_locked` is incremented
- Warning message added to response
- No error thrown (continues processing)

---

### Override Behavior (override_grades=true)

When `override_grades=true`, the system updates ALL existing grades regardless of status:

**Updatable Statuses**:
- ✅ ALL statuses (DRAFT, PENDING, REVIEWED, SUBMITTED, APPROVED, REJECTED, null)

**What Happens**:
- All existing grades are updated
- Status is reset to `DRAFT`
- No grades are locked
- Use with caution in production

---

## Use Cases

### Use Case 1: Initial Grade Entry
**Scenario**: Teachers entering grades for the first time  
**Parameter**: `override_grades=false` (default)  
**Reason**: Most grades will be new or in DRAFT status

```bash
POST /api/grading/sections/{id}/grades/upload/
  ?academic_year={id}
  &subject_id={id}
```

---

### Use Case 2: Correcting Draft Grades
**Scenario**: Teacher made mistakes in draft grades and needs to fix them  
**Parameter**: `override_grades=false` (default)  
**Reason**: Only DRAFT grades need updating

```bash
POST /api/grading/sections/{id}/grades/upload/
  ?academic_year={id}
  &subject_id={id}
```

**Result**: Only draft grades updated, approved/submitted grades remain unchanged

---

### Use Case 3: Complete Grade Replacement
**Scenario**: System migration or major correction needed  
**Parameter**: `override_grades=true`  
**Reason**: Need to update ALL grades including approved ones

```bash
POST /api/grading/sections/{id}/grades/upload/
  ?academic_year={id}
  &subject_id={id}
  &override_grades=true
```

**⚠️ Warning**: This will reset ALL grades to DRAFT status!

---

### Use Case 4: Partial Update After Approval
**Scenario**: Some grades were approved, but teacher wants to update only new/draft entries  
**Parameter**: `override_grades=false` (default)  
**Reason**: Protect already approved grades

```bash
POST /api/grading/sections/{id}/grades/upload/
  ?academic_year={id}
  &subject_id={id}
```

**Result**: 
- Approved grades: **Skipped** (locked)
- Draft grades: **Updated**
- New students: **Created**

---

## Response Format

### With Locked Grades (override_grades=false)

```json
{
  "detail": "Successfully processed 50 students. Created 100 new grades, updated 30 existing grades. 20 grades were locked and not updated (use override_grades=true to force update).",
  "statistics": {
    "total_rows": 50,
    "students_processed": 50,
    "grades_created": 100,
    "grades_updated": 30,
    "grades_locked": 20,
    "grades_skipped": 0,
    "warning_count": 20,
    "error_count": 0
  },
  "warnings": [
    {
      "row": 5,
      "student_id": "S2024001",
      "assessment": "Final Grade",
      "warning": "Grade with status \"Approved\" cannot be updated. Use override_grades=true to force update."
    },
    {
      "row": 8,
      "student_id": "S2024003",
      "assessment": "Quiz 1",
      "warning": "Grade with status \"Submitted\" cannot be updated. Use override_grades=true to force update."
    }
  ],
  "errors": []
}
```

---

### With Override Enabled (override_grades=true)

```json
{
  "detail": "Successfully processed 50 students. Created 100 new grades, updated 50 existing grades.",
  "statistics": {
    "total_rows": 50,
    "students_processed": 50,
    "grades_created": 100,
    "grades_updated": 50,
    "grades_locked": 0,
    "grades_skipped": 0,
    "warning_count": 0,
    "error_count": 0
  },
  "warnings": [],
  "errors": []
}
```

---

## Implementation Details

### Code Logic

```python
# Check if grade exists
if existing_grade:
    # Determine if we can update
    can_update = override_grades or existing_grade.status in [Grade.Status.DRAFT, None]
    
    if can_update:
        # Update the grade
        existing_grade.score = score
        existing_grade.status = Grade.Status.DRAFT  # Reset to DRAFT
        existing_grade.updated_by = user
        grades_to_update.append(existing_grade)
        stats['grades_updated'] += 1
    else:
        # Grade is locked
        stats['grades_locked'] += 1
        stats['warnings'].append({
            'row': row_number,
            'student_id': id_number,
            'assessment': assessment_col,
            'warning': f'Grade with status "{existing_grade.get_status_display()}" cannot be updated. Use override_grades=true to force update.'
        })
else:
    # Create new grade (always allowed)
    new_grade = Grade(...)
    grades_to_create.append(new_grade)
    stats['grades_created'] += 1
```

---

## Best Practices

### ✅ DO

1. **Use default (false) for regular updates**
   - Protects approved grades
   - Prevents accidental overwrites
   - Safer for production use

2. **Test with small dataset first**
   - Upload 5-10 students
   - Check locked grades count
   - Review warnings before proceeding

3. **Use override=true only when necessary**
   - System migrations
   - Known data corrections
   - With proper authorization

4. **Review warnings carefully**
   - Check which grades are locked
   - Verify if those should remain unchanged
   - Decide if override is needed

### ❌ DON'T

1. **Don't use override=true by default**
   - Risk of overwriting approved grades
   - May lose audit trail
   - Can cause confusion

2. **Don't ignore locked grade warnings**
   - Warnings indicate protected grades
   - May need administrator review
   - Could indicate workflow issues

3. **Don't override without backup**
   - Always have backup before mass override
   - Document reason for override
   - Get approval if needed

---

## Security Considerations

### Permission Requirements
- Same permissions as regular grade entry
- `Permissions.Student.GRADEBOOK_GRADE_ENTRY`
- No special permission needed for override

**Recommendation**: Consider adding separate permission for override in future:
```python
# Future enhancement
if override_grades and not user.has_permission('OVERRIDE_APPROVED_GRADES'):
    return error('Insufficient permissions to override approved grades')
```

---

## Frontend Implementation

### UI/UX Recommendations

#### 1. Checkbox with Warning
```jsx
<Checkbox 
  label="Override approved/submitted grades"
  checked={overrideGrades}
  onChange={setOverrideGrades}
/>
{overrideGrades && (
  <Alert severity="warning">
    ⚠️ This will update ALL grades, including approved ones. 
    All grades will be reset to DRAFT status.
  </Alert>
)}
```

#### 2. Two-Step Confirmation
```javascript
const handleUpload = async () => {
  if (overrideGrades) {
    const confirmed = await confirmDialog({
      title: 'Override Approved Grades?',
      message: 'This will update ALL grades including approved ones. Continue?',
      confirmText: 'Yes, Override All',
      cancelText: 'Cancel'
    });
    
    if (!confirmed) return;
  }
  
  // Proceed with upload
  uploadFile({ overrideGrades });
};
```

#### 3. Show Locked Grades Count
```jsx
{response.statistics.grades_locked > 0 && (
  <Alert severity="info">
    {response.statistics.grades_locked} approved/submitted grades were not updated.
    <Button onClick={() => setOverrideGrades(true)}>
      Upload Again with Override
    </Button>
  </Alert>
)}
```

---

## Testing

### Test Cases

#### 1. Default Behavior (override_grades=false)
```python
def test_respects_approved_grades():
    # Create approved grade
    grade = Grade.objects.create(
        assessment=assessment,
        student=student,
        score=85,
        status=Grade.Status.APPROVED
    )
    
    # Upload with new score
    response = upload_grades(override_grades=False, score=90)
    
    # Assert
    assert response['statistics']['grades_locked'] == 1
    grade.refresh_from_db()
    assert grade.score == 85  # Unchanged
    assert grade.status == Grade.Status.APPROVED  # Unchanged
```

#### 2. Override Behavior (override_grades=true)
```python
def test_overrides_approved_grades():
    # Create approved grade
    grade = Grade.objects.create(
        assessment=assessment,
        student=student,
        score=85,
        status=Grade.Status.APPROVED
    )
    
    # Upload with override
    response = upload_grades(override_grades=True, score=90)
    
    # Assert
    assert response['statistics']['grades_updated'] == 1
    assert response['statistics']['grades_locked'] == 0
    grade.refresh_from_db()
    assert grade.score == 90  # Updated
    assert grade.status == Grade.Status.DRAFT  # Reset to DRAFT
```

#### 3. Mixed Statuses
```python
def test_mixed_statuses():
    # Create grades with different statuses
    Grade.objects.create(status=Grade.Status.DRAFT, score=85)
    Grade.objects.create(status=Grade.Status.APPROVED, score=90)
    Grade.objects.create(status=Grade.Status.PENDING, score=78)
    
    # Upload without override
    response = upload_grades(override_grades=False)
    
    # Assert
    assert response['statistics']['grades_updated'] == 1  # Only DRAFT
    assert response['statistics']['grades_locked'] == 2   # APPROVED + PENDING
```

---

## Changelog

### Version 2.2 (Current)
- ✅ Added `override_grades` parameter
- ✅ Added `grades_locked` counter in response
- ✅ Added warning messages for locked grades
- ✅ Updated documentation

### Future Enhancements
- [ ] Separate permission for override capability
- [ ] Audit log for override actions
- [ ] Bulk status preservation option
- [ ] Grade comparison before override

---

## FAQ

### Q: What happens to grade status when overridden?
**A**: All updated grades are reset to `DRAFT` status, regardless of their previous status.

### Q: Can I override only specific statuses?
**A**: No, `override_grades=true` overrides ALL statuses. Use default behavior to protect approved grades.

### Q: Do locked grades cause errors?
**A**: No, they generate warnings but don't stop the upload. Other grades are still processed.

### Q: How do I know which grades were locked?
**A**: Check the `warnings` array in the response. Each warning includes row number, student ID, and assessment name.

### Q: Can I revert an override?
**A**: No automatic revert. You'll need to re-upload the original data or restore from backup.

### Q: Does override require special permissions?
**A**: Currently no, but this may be added in a future version for security.

---

**Version**: 2.2  
**Last Updated**: October 28, 2025  
**Feature**: Override Grades Protection System

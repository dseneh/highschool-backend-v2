# Grading Style Auto-Regeneration

## Overview

The system now automatically regenerates gradebooks with appropriate default assessments when the grading style is changed in the school settings. This ensures that all gradebooks have the correct assessment structure for the selected grading mode.

## How It Works

### 1. Detection of Grading Style Changes

When a PATCH request is made to update grading settings (`/api/v1/settings/schools/{school_id}/grading/`), the system:

1. **Captures the old grading style** before applying updates
2. **Compares with the new grading style** from the request
3. **Flags the change** if the grading style has been modified

### 2. Template Validation

Before allowing the grading style change, the system validates that:

- **Active default assessment templates exist** for the school
- Templates are properly configured for the new grading style

If no templates are found:
```json
{
  "success": false,
  "error": "no_templates_found",
  "message": "Cannot change grading style to 'multiple_entry' because no active default assessment templates are configured for this school. Please create templates before changing the grading style."
}
```

### 3. Settings Update

If validation passes, the system proceeds to update the grading settings using the standard update process.

### 4. Gradebook Regeneration

After successful settings update, if the grading style changed:

1. **Gets all active academic years** for the school
2. **Processes each gradebook** in those academic years
3. **Checks for existing grades** with scores to prevent data loss
4. **Deletes old assessments** (if no grades exist)
5. **Generates new assessments** from templates based on the new grading style
6. **Collects statistics** on the regeneration process

## Safety Features

### Data Loss Prevention

The system will **NOT regenerate** a gradebook if it contains grades with scores (unless `force_regenerate=true`):

```json
{
  "gradebook_id": "uuid-here",
  "gradebook_name": "Math 101 - Section A",
  "academic_year": "2023-2024",
  "error": "Skipped: 25 grades with scores exist. Cannot regenerate to avoid data loss."
}
```

This ensures that:
- **Teachers' work is preserved**
- **Student data is not lost**
- **Grading integrity is maintained**

### Assessment Type Mismatch Detection

The system detects when existing assessment types don't match the new templates:

```json
{
  "gradebook_id": "uuid-here",
  "gradebook_name": "Science 201",
  "academic_year": "2023-2024",
  "warning": "Assessment types mismatch detected. Existing: ['final_exam', 'quiz'], Templates: ['assessment', 'final_grade']. Skipped due to 30 grades with scores. Use force_regenerate=True to regenerate anyway (will delete grades)."
}
```

Benefits:
- **Identifies incompatible structures** between old and new grading styles
- **Warns before data loss** when assessment types change
- **Suggests force_regenerate** option for intentional changes

### Force Regenerate Option

For intentional grading structure changes, use `force_regenerate=true`:

**Endpoint**: `PATCH /api/v1/settings/schools/{school_id}/grading/?force_regenerate=true`

**⚠️ WARNING**: This will **DELETE ALL EXISTING GRADES** in affected gradebooks!

**Use Cases**:
- Starting a new academic year with different grading structure
- Correcting a misconfigured grading system
- Switching from one assessment type system to another

**Response with Force Regenerate**:
```json
{
  "success": true,
  "message": "Grading settings updated and 12 gradebook(s) regenerated successfully. ⚠️ 5 gradebook(s) force-regenerated (150 grades deleted). ⚠️ 5 warning(s) - see details",
  "gradebook_regeneration": {
    "statistics": {
      "gradebooks_processed": 12,
      "grades_deleted": 150,
      "force_regenerated": 5,
      "warnings": [
        {
          "gradebook_id": "...",
          "gradebook_name": "Math 101",
          "academic_year": "2023-2024",
          "warning": "Force regenerated: 30 grades with scores deleted"
        }
      ]
    },
    "force_regenerate_used": true
  }
}
```

### Error Handling

Each gradebook is processed individually with try-catch blocks:
- Errors in one gradebook don't stop processing of others
- All errors are collected and reported
- Partial success is supported

## API Response

### Successful Regeneration (No Grades)

```json
{
  "success": true,
  "message": "Grading settings updated and 12 gradebook(s) regenerated successfully",
  "data": {
    // ... updated settings ...
  },
  "gradebook_regeneration": {
    "success": true,
    "message": "Gradebooks regenerated successfully",
    "statistics": {
      "academic_years_processed": 1,
      "gradebooks_processed": 12,
      "assessments_deleted": 48,
      "assessments_created": 144,
      "grades_deleted": 0,
      "force_regenerated": 0,
      "errors": [],
      "warnings": []
    },
    "force_regenerate_used": false
  }
}
```

### Successful with Force Regenerate

```json
{
  "success": true,
  "message": "Grading settings updated and 12 gradebook(s) regenerated successfully. ⚠️ 5 gradebook(s) force-regenerated (150 grades deleted). ⚠️ 5 warning(s) - see details",
  "data": {
    // ... updated settings ...
  },
  "gradebook_regeneration": {
    "success": true,
    "message": "Gradebooks regenerated successfully",
    "statistics": {
      "academic_years_processed": 1,
      "gradebooks_processed": 12,
      "assessments_deleted": 180,
      "assessments_created": 144,
      "grades_deleted": 150,
      "force_regenerated": 5,
      "errors": [],
      "warnings": [
        {
          "gradebook_id": "uuid-here",
          "gradebook_name": "Math 101",
          "academic_year": "2023-2024",
          "warning": "Force regenerated: 30 grades with scores deleted"
        }
      ]
    },
    "force_regenerate_used": true
  }
}
```

### Partial Success (Assessment Type Mismatch)

```json
{
  "success": true,
  "message": "Grading settings updated and 8 gradebook(s) regenerated successfully. ⚠️ 4 warning(s) - see details",
  "data": {
    // ... updated settings ...
  },
  "gradebook_regeneration": {
    "success": true,
    "message": "Gradebooks regenerated successfully",
    "statistics": {
      "academic_years_processed": 1,
      "gradebooks_processed": 8,
      "assessments_deleted": 32,
      "assessments_created": 96,
      "grades_deleted": 0,
      "force_regenerated": 0,
      "errors": [
        {
          "gradebook_id": "uuid-here",
          "gradebook_name": "Science 201",
          "academic_year": "2023-2024",
          "error": "Skipped: 30 grades with scores exist. Cannot regenerate to avoid data loss."
        }
      ],
      "warnings": [
        {
          "gradebook_id": "uuid-here",
          "gradebook_name": "History 301",
          "academic_year": "2023-2024",
          "warning": "Assessment types mismatch detected. Existing: ['final_exam', 'quiz'], Templates: ['assessment', 'final_grade']. Skipped due to 25 grades with scores. Use force_regenerate=True to regenerate anyway (will delete grades)."
        }
      ]
    },
    "force_regenerate_used": false
  }
}
```

### No Templates Available

```json
{
  "success": false,
  "error": "no_templates_found",
  "message": "Cannot change grading style to 'multiple_entry' because no active default assessment templates are configured for this school. Please create templates before changing the grading style."
}
```

## Implementation Details

### New Utility Function

**Location**: `grading/utils.py`

```python
def regenerate_gradebooks_for_grading_style_change(school, new_grading_style, created_by=None, force_regenerate=False):
    """
    Regenerate gradebooks and assessments when grading style changes.
    
    Args:
        school: School instance
        new_grading_style: New grading style ('single_entry' or 'multiple_entry')
        created_by: User who triggered the change (optional)
        force_regenerate: If True, regenerate even if grades exist (data will be lost)
        
    Returns:
        Dictionary with statistics:
        {
            'academic_years_processed': int,
            'gradebooks_processed': int,
            'assessments_deleted': int,
            'assessments_created': int,
            'grades_deleted': int,
            'force_regenerated': int,
            'errors': list,
            'warnings': list
        }
        
    Raises:
        ValueError: If no templates found for the grading style
    """
```

**Key Features**:
- ✅ Detects assessment type mismatches between existing and templates
- ✅ Compares existing assessment types with template assessment types
- ✅ Warns when types don't match but grades exist
- ✅ Supports `force_regenerate` to override safety checks
- ✅ Returns separate `errors` and `warnings` arrays

### Updated View

**Location**: `settings/views/grading.py`

The `GradingSettingsView.patch()` method now:

1. Detects grading style changes
2. Validates templates before allowing the change
3. Accepts `force_regenerate` query parameter
4. Updates settings
5. Triggers gradebook regeneration
6. Returns comprehensive statistics with errors and warnings

## Grading Styles

### Single Entry Mode

**Characteristics**:
- One "Final Grade" assessment per marking period
- Direct grade entry without multiple assessments
- Simple, straightforward grading

**Default Assessment Structure**:
- Assessment name: Configurable (default: "Final Grade")
- One assessment per marking period
- Direct percentage or letter grade entry

### Multiple Entry Mode

**Characteristics**:
- Multiple assessments per marking period
- Weighted or unweighted averages
- Detailed grading breakdown

**Default Assessment Structure**:
- Assessments generated from `DefaultAssessmentTemplate`
- Applied based on `MarkingPeriodAssessmentRule`
- Various types: quizzes, tests, homework, projects, etc.

## Best Practices

### Before Changing Grading Style

1. **Create or verify templates**:
   - Ensure `DefaultAssessmentTemplate` records exist for your school
   - Verify `MarkingPeriodAssessmentRule` is configured
   - Test templates with preview endpoints

2. **Check for existing grades**:
   - Review which gradebooks have grades entered
   - Communicate with teachers about the change
   - Consider doing this at the start of an academic year

3. **Backup data** (if needed):
   - Export current grades if switching mid-year
   - Document current assessment structure

### After Changing Grading Style

1. **Review regeneration statistics**:
   - Check how many gradebooks were processed
   - Review any errors in the response
   - Follow up on skipped gradebooks

2. **Verify gradebook structure**:
   - Check a sample gradebook
   - Confirm assessments match templates
   - Validate due dates and weights

3. **Communicate with teachers**:
   - Inform them of the change
   - Provide training if needed
   - Address any concerns

## Use Cases

### Scenario 1: School Starting Out

**Situation**: New school starting with simple grading, planning to expand

**Initial State**: Single entry mode
**Target State**: Multiple entry mode

**Steps**:
1. Create default assessment templates for the school
2. Configure marking period assessment rules
3. Change grading style in settings
4. System automatically regenerates all gradebooks
5. Teachers now have detailed assessment structure

### Scenario 2: Simplifying Grading

**Situation**: School wants to simplify from complex to simple grading

**Initial State**: Multiple entry mode with many assessments
**Target State**: Single entry mode

**Steps**:
1. Ensure single_entry_assessment_name is configured
2. Change grading style in settings
3. System attempts to regenerate gradebooks
4. Gradebooks with existing grades are skipped (data protection)
5. New/empty gradebooks get single "Final Grade" assessment

### Scenario 3: Mid-Year Adjustment with Assessment Type Change

**Situation**: School realizes assessment types in templates don't match current structure

**Challenge**: 
- Current gradebooks use assessment types: `['quiz', 'test', 'homework']`
- New templates use assessment types: `['assessment', 'final_grade']`
- Many gradebooks have grades already entered

**Process**:

1. **First attempt (without force)**:
   ```bash
   PATCH /api/v1/settings/schools/{school_id}/grading/
   { "grading_style": "single_entry" }
   ```
   
   **Result**:
   - Empty gradebooks: Regenerated ✓
   - Gradebooks with grades: Skipped with warning
   - Warning message: "Assessment types mismatch detected. Use force_regenerate=True to regenerate anyway"

2. **Review warnings**:
   ```json
   {
     "warnings": [
       {
         "gradebook_id": "...",
         "gradebook_name": "Math 101",
         "warning": "Assessment types mismatch detected. Existing: ['homework', 'quiz', 'test'], Templates: ['assessment', 'final_grade']. Skipped due to 150 grades with scores. Use force_regenerate=True to regenerate anyway (will delete grades)."
       }
     ]
   }
   ```

3. **Decision point**:
   - **Option A**: Keep existing gradebooks with old structure (partial migration)
   - **Option B**: Force regenerate to align all gradebooks (data loss)
   - **Option C**: Export grades, force regenerate, then re-import

4. **Force regeneration** (if decided):
   ```bash
   PATCH /api/v1/settings/schools/{school_id}/grading/?force_regenerate=true
   { "grading_style": "single_entry" }
   ```
   
   **Result**:
   - All gradebooks regenerated
   - 150 grades deleted
   - New assessment structure applied
   - Warnings show what was deleted

**Outcome**:
- ✓ Consistent assessment structure across all gradebooks
- ⚠️ Lost existing grade data (intentional with force flag)
- ✓ Ready for new grading period with correct structure

## Technical Notes

### Performance Considerations

- **Batch Processing**: All gradebooks in active academic years are processed
- **Transaction Safety**: Each gradebook is processed in its own try-catch
- **Database Queries**: Optimized with select_related to minimize queries
- **Async Consideration**: For large schools (>100 gradebooks), consider async processing

### Database Impact

**Deletions**:
- Old `Assessment` records are deleted
- Related `Grade` records are deleted (CASCADE)
- Only affects gradebooks without scored grades

**Insertions**:
- New `Assessment` records created from templates
- New `Grade` records auto-created for students

### Error Recovery

If regeneration fails mid-process:
- Settings are already updated (cannot be rolled back automatically)
- Processed gradebooks have new assessments
- Unprocessed gradebooks retain old structure
- Errors array shows what failed

**Recovery Steps**:
1. Review error messages in response
2. Fix underlying issues (templates, permissions, etc.)
3. Manually trigger regeneration for failed gradebooks using management command
4. Or change grading style back and forth to retry

## Related Documentation

- [Grading Menu Structure](../grading_menu_structure.json)
- [School System Settings](../SCHOOL_SYSTEM_SETTINGS.md)
- [Final Grades API](../FINAL_GRADES_API.md)
- [Default Assessment Templates](./DEFAULT_ASSESSMENT_TEMPLATES.md)
- [Marking Period Assessment Rules](./MARKING_PERIOD_ASSESSMENT_RULES.md)

## Future Enhancements

Potential improvements for this feature:

1. **Dry Run Mode**: Preview what would be regenerated without actually doing it
2. **Async Processing**: Background job for large schools
3. **Notification System**: Email teachers when their gradebooks are regenerated
4. **Rollback Option**: Save old assessment structure for rollback
5. **Gradebook Selection**: Allow selective regeneration of specific gradebooks
6. **Progress Tracking**: Real-time progress updates via websocket

## Troubleshooting

### "No templates found" Error

**Problem**: Cannot change grading style due to missing templates

**Solution**:
1. Navigate to `/api/v1/grading/default-assessment-templates/`
2. Create templates for your school
3. Ensure `is_active=True`
4. Try changing grading style again

### Gradebooks Not Regenerating

**Problem**: Settings updated but gradebooks weren't regenerated

**Possible Causes**:
1. **Existing grades**: Gradebooks have scores, system preserved them
2. **No active academic years**: No academic years marked as active
3. **Gradebooks inactive**: Gradebooks have `active=False`

**Solution**:
1. Check regeneration statistics in response
2. Review errors array for specific issues
3. Use `force_regenerate=true` if intentional data loss is acceptable
4. Manually regenerate using management command if needed

### Assessment Type Mismatch Warning

**Problem**: Warning about assessment types not matching templates

**Message Example**:
```
Assessment types mismatch detected. Existing: ['quiz', 'test'], 
Templates: ['assessment', 'final_grade']. Skipped due to 30 grades 
with scores. Use force_regenerate=True to regenerate anyway.
```

**Understanding**:
- System detected that existing assessments use different types than templates
- This usually happens when switching between grading systems
- Gradebook was preserved to prevent data loss

**Solutions**:

1. **Keep existing structure** (Recommended for mid-year):
   - Do nothing
   - Gradebook keeps current assessment structure
   - Only new/empty gradebooks get new structure
   - Accept partial migration

2. **Export and force regenerate**:
   ```bash
   # 1. Export grades first
   GET /api/v1/grading/gradebooks/{gradebook_id}/export/
   
   # 2. Force regenerate
   PATCH /api/v1/settings/schools/{school_id}/grading/?force_regenerate=true
   { "grading_style": "new_style" }
   
   # 3. Re-import grades (if compatible)
   POST /api/v1/grading/gradebooks/{gradebook_id}/import/
   ```

3. **Wait for new academic year**:
   - Leave current gradebooks as-is
   - New academic year will use new templates automatically
   - Clean slate, no data loss

### Partial Regeneration

**Problem**: Some gradebooks regenerated, others didn't

**Expected Behavior**: This is normal and intentional
- Gradebooks without scores: Regenerated ✓
- Gradebooks with scores: Preserved (skipped) ✓
- Gradebooks with assessment type mismatch: Warning ⚠️

**Action**:
1. Review statistics to see which were processed
2. Check `errors` array for skipped gradebooks
3. Check `warnings` array for type mismatches
4. Decide if manual intervention needed for gradebooks with data
5. Consider using `force_regenerate=true` for complete migration

### Force Regenerate Didn't Work

**Problem**: Used `force_regenerate=true` but some gradebooks still not regenerated

**Possible Causes**:
1. **Processing error**: Check `errors` array in response
2. **Invalid templates**: Templates don't have proper assessment types
3. **Permission issues**: User lacks permission to delete grades
4. **Database constraints**: Foreign key issues

**Solution**:
1. Review `errors` array in API response
2. Check application logs for detailed error messages
3. Verify templates are valid and active
4. Ensure user has proper permissions
5. Try regenerating one gradebook at a time to isolate issue

## API Endpoint Reference

### Update Grading Settings (with Auto-Regeneration)

**Endpoint**: `PATCH /api/v1/settings/schools/{school_id}/grading/`

**Query Parameters**:
- `force_regenerate` (boolean, optional): If `true`, regenerate all gradebooks even if grades exist
  - Default: `false`
  - **⚠️ WARNING**: Setting to `true` will DELETE existing grades!

**Request Body**:
```json
{
  "grading_style": "multiple_entry"
}
```

**Example Calls**:

1. **Safe Regeneration** (Default - preserves existing grades):
   ```bash
   PATCH /api/v1/settings/schools/{school_id}/grading/
   Content-Type: application/json
   
   {
     "grading_style": "multiple_entry"
   }
   ```

2. **Force Regeneration** (Deletes existing grades):
   ```bash
   PATCH /api/v1/settings/schools/{school_id}/grading/?force_regenerate=true
   Content-Type: application/json
   
   {
     "grading_style": "single_entry"
   }
   ```

**Response**: See "API Response" section above

**Side Effects**:
- Updates grading settings
- Regenerates gradebooks if grading_style changed
- May delete assessments in empty gradebooks (always)
- May delete assessments with grades (only if `force_regenerate=true`)
- Creates new assessments from templates

**Idempotency**: Changing to the same grading style is a no-op

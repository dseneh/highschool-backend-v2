# Settings System Documentation

## Overview

The Settings system provides centralized control over system behavior, allowing schools to configure how different modules operate. Currently supports grading system configuration at the **school level**.

---

## Grading Settings

### Overview

Grading settings control how grades are captured and managed in the system. There are two primary grading modes:

1. **Single Entry Mode** - Captures only final grades (one assessment per marking period)
2. **Multiple Entry Mode** - Captures multiple assessments (quizzes, tests, etc.) with automatic calculation

### Configuration Level

Settings are defined at the **School Level** (`GradingSettings`):
- Default settings apply to **all academic years** within the school
- Consistent behavior across all years
- Easy to manage and understand

---

## API Endpoints

### School Grading Settings

#### Get School Grading Settings

**GET** `/api/v1/settings/schools/{school_id}/grading/`

Get grading settings for a school. Creates default settings if none exist.

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "active": true,
    "school": {
      "id": "uuid",
      "name": "Test High School"
    },
    "grading_style": "multiple_entry",
    "grading_style_display": "Multiple Entry (Assessments & Final Grades)",
    "single_entry_assessment_name": "Final Grade",
    "use_default_templates": true,
    "auto_calculate_final_grade": true,
    "default_calculation_method": "weighted",
    "calculation_method_display": "Weighted Average",
    "require_grade_approval": false,
    "use_letter_grades": true,
    "allow_teacher_override": true,
    "lock_grades_after_semester": false,
    "notes": null,
    "created_at": "2025-10-23T10:00:00Z",
    "updated_at": "2025-10-23T10:00:00Z"
  },
  "is_new": false
}
```

---

#### Update School Grading Settings

**PATCH** `/api/v1/settings/schools/{school_id}/grading/`

Update grading settings for a school.

**Request Body:** (all fields optional)
```json
{
  "grading_style": "single_entry",
  "single_entry_assessment_name": "Final Grade",
  "default_calculation_method": "average",
  "use_letter_grades": true,
  "require_grade_approval": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Grading settings updated successfully",
  "data": {
    "id": "uuid",
    "grading_style": "single_entry",
    // ... other fields
  }
}
```

---

#### Quick Grading Style Check

**GET** `/api/v1/settings/schools/{school_id}/grading-style/`

Quick endpoint to check grading style for a school.

**Response:**
```json
{
  "success": true,
  "school_id": "uuid",
  "school_name": "Test High School",
  "grading_style": "single_entry",
  "is_single_entry": true,
  "is_multiple_entry": false
}
```

---

## Grading Modes

### Single Entry Mode

**Configuration:**
```json
{
  "grading_style": "single_entry",
  "single_entry_assessment_name": "Final Grade"
}
```

**Behavior:**
- One assessment per gradebook per marking period
- Assessment type must have `is_single_entry = True`
- Default assessment name: "Final Grade" (configurable)
- No template-based generation
- Manual grade entry only
- Max score: 100 (standard percentage scale)

**Use Cases:**
- Simple grade reporting
- Elementary schools
- Pass/Fail courses
- Schools transitioning to detailed grading

**Assessment Generation:**
```python
# For each marking period, creates:
Assessment(
    name="Final Grade",
    assessment_type=<single_entry_type>,
    max_score=100,
    weight=1,
    is_calculated=False,
    due_date=marking_period.end_date
)
```

---

### Multiple Entry Mode

**Configuration:**
```json
{
  "grading_style": "multiple_entry",
  "use_default_templates": true,
  "default_calculation_method": "weighted",
  "auto_calculate_final_grade": true
}
```

**Behavior:**
- Multiple assessments per marking period
- Uses `DefaultAssessmentTemplate` system
- Follows `MarkingPeriodAssessmentRule` configurations
- Automatic grade calculation based on weights
- Detailed tracking of student performance

**Use Cases:**
- Standard K-12 grading
- High schools with multiple assessment types
- Detailed performance tracking
- Standards-based grading

**Assessment Generation:**
```python
# Uses existing template system:
# - Reads DefaultAssessmentTemplate
# - Applies MarkingPeriodAssessmentRule
# - Creates multiple assessments per marking period
```

---

## Field Descriptions

### GradingSettings Model Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `school` | ForeignKey | required | School these settings apply to |
| `grading_style` | CharField | `multiple_entry` | Single or multiple entry mode |
| `single_entry_assessment_name` | CharField | `"Final Grade"` | Name for single-entry assessments |
| `use_default_templates` | BooleanField | `True` | Auto-generate from templates (multiple entry) |
| `auto_calculate_final_grade` | BooleanField | `True` | Calculate final grades automatically |
| `default_calculation_method` | CharField | `"weighted"` | How to calculate grades (average/weighted) |
| `require_grade_approval` | BooleanField | `False` | Require approval before finalizing |
| `use_letter_grades` | BooleanField | `True` | Display letter grades |
| `allow_teacher_override` | BooleanField | `True` | Allow manual grade adjustments |
| `lock_grades_after_semester` | BooleanField | `False` | Prevent edits after semester ends |
| `notes` | TextField | `null` | Additional configuration notes |

---

## Use Cases & Examples

### Example 1: Switch to Single Entry

**Scenario:** Elementary school wants simple final grade entry.

**API Call:**
```bash
PATCH /api/v1/settings/schools/abc-123/grading/
{
  "grading_style": "single_entry",
  "single_entry_assessment_name": "Final Grade"
}
```

**Result:**
- All future gradebooks will generate 1 assessment per marking period
- Existing gradebooks remain unchanged
- Teachers enter final percentage directly

---

### Example 2: Configure Multiple Entry with Weighted Average

**Scenario:** High school wants detailed assessment tracking.

**API Call:**
```bash
PATCH /api/v1/settings/schools/abc-123/grading/
{
  "grading_style": "multiple_entry",
  "use_default_templates": true,
  "default_calculation_method": "weighted",
  "auto_calculate_final_grade": true
}
```

**Result:**
- Assessments generated from templates
- Grades calculated using weights
- Automatic final grade computation

---

### Example 3: Disable Automatic Calculation

**Scenario:** School wants manual control over final grades.

**API Call:**
```bash
PATCH /api/v1/settings/schools/abc-123/grading/
{
  "auto_calculate_final_grade": false,
  "allow_teacher_override": true
}
```

**Result:**
- Teachers must enter final grades manually
- Can still use multiple assessments for tracking
- Full control over final grades

---

## Integration with Grading System

### Assessment Generation Function

The main function that respects settings:

```python
from grading.utils import generate_assessments_for_gradebook_with_settings

result = generate_assessments_for_gradebook_with_settings(gradebook, created_by)

# Returns:
{
    'mode': 'single_entry' or 'multiple_entry',
    'assessments_created': 4,
    'assessment_ids': ['uuid1', 'uuid2', ...],
    'message': 'Generated 4 assessments in single_entry mode'
}
```

### How It Works

1. **Lookup Settings:**
   ```python
   school_settings = gradebook.section.school.grading_settings
   grading_style = school_settings.grading_style
   ```

2. **Generate Based on Mode:**
   - If `single_entry`: Create one "Final Grade" per marking period
   - If `multiple_entry`: Use existing template system

3. **Return Results:**
   - List of created assessments
   - Mode used
   - Summary message

---

## Database Schema

### GradingSettings Table

```sql
CREATE TABLE settings_gradingsettings (
    id UUID PRIMARY KEY,
    school_id UUID NOT NULL UNIQUE,
    grading_style VARCHAR(20) DEFAULT 'multiple_entry',
    single_entry_assessment_name VARCHAR(100) DEFAULT 'Final Grade',
    use_default_templates BOOLEAN DEFAULT TRUE,
    auto_calculate_final_grade BOOLEAN DEFAULT TRUE,
    default_calculation_method VARCHAR(20) DEFAULT 'weighted',
    require_grade_approval BOOLEAN DEFAULT FALSE,
    use_letter_grades BOOLEAN DEFAULT TRUE,
    allow_teacher_override BOOLEAN DEFAULT TRUE,
    lock_grades_after_semester BOOLEAN DEFAULT FALSE,
    notes TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by_id UUID,
    updated_by_id UUID,
    
    FOREIGN KEY (school_id) REFERENCES core_school(id),
    FOREIGN KEY (created_by_id) REFERENCES users_customuser(id),
    FOREIGN KEY (updated_by_id) REFERENCES users_customuser(id)
);
```

---

## Best Practices

### 1. Default Settings

Always create settings with sensible defaults:
```python
GradingSettings.objects.create(
    school=school,
    grading_style='multiple_entry',  # Most common
    use_default_templates=True,
    default_calculation_method='weighted',
    created_by=user
)
```

### 2. Testing Configuration

Before changing grading style:
- Review existing gradebooks
- Communicate changes to teachers
- Test with sample gradebook first
- Monitor assessment generation

### 3. Migration Strategy

When switching from multiple to single entry:
- Existing assessments remain unchanged
- Only NEW gradebooks use single entry
- Can coexist during transition
- Teachers can finish current marking periods

### 4. Gradebook-Specific Overrides

While settings are school-wide, individual gradebooks can still:
- Manually add/remove assessments
- Adjust weights
- Override calculated grades (if allowed)

---

## API Response Codes

| Code | Meaning | Common Causes |
|------|---------|---------------|
| 200 | Success | Valid request, settings updated |
| 400 | Bad Request | Invalid field values, validation errors |
| 404 | Not Found | School ID doesn't exist |
| 500 | Server Error | Database issues, system errors |

---

## Troubleshooting

### Settings Not Taking Effect

**Problem:** Changed settings but assessments still generating old way.

**Solution:**
- Settings only affect NEW gradebooks
- Existing gradebooks retain their assessments
- Regenerate assessments for existing gradebooks if needed

---

### Assessment Type Not Found

**Problem:** Single entry mode fails with "AssessmentType not found".

**Solution:**
- System auto-creates single-entry type if missing
- Check that school has at least one active assessment type
- Verify `is_single_entry=True` exists

---

### Template Generation Not Working

**Problem:** Multiple entry mode creates no assessments.

**Solution:**
- Check that DefaultAssessmentTemplate exists for school
- Verify MarkingPeriodAssessmentRule are configured
- Ensure `auto_generate=True` on rules
- Check that marking periods exist for academic year

---

## Future Enhancements

Potential additions to settings system:

1. **Academic Year Overrides** - Allow year-specific settings (if needed)
2. **Attendance Settings** - Configure attendance policies
3. **Finance Settings** - Payment and fee configurations
4. **Report Card Settings** - Customize report card generation
5. **Notification Settings** - Control email/SMS notifications

---

## Related Documentation

- **Grading System**: See `grading/README.md`
- **Assessment Templates**: See `docs/assessment_templates.md`
- **API Overview**: See main `README.md`

---

**Last Updated:** October 23, 2025
**Version:** 1.0 (Simplified - School Level Only)
**Module:** Settings App

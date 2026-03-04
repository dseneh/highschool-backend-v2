# Grading System Guide

Complete guide to the grading system for high school management.

---

## Table of Contents

- [Overview](#overview)
- [Core Concepts](#core-concepts)
- [Grading Modes](#grading-modes)
- [Models](#models)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Workflows](#workflows)
- [Management Commands](#management-commands)
- [Troubleshooting](#troubleshooting)

---

## Overview

A comprehensive Django-based grading system supporting:

- **Gradebook Management**: Year-specific gradebooks for sections and subjects
- **Two Grading Modes**: Simple single-entry or detailed multiple-entry
- **Auto-Generation**: Assessments created automatically based on school settings
- **Three Calculation Methods**: Average, weighted, and cumulative
- **Grade Workflow**: Draft → Pending → Reviewed → Approved
- **Performance Optimized**: Indexes and efficient queries

---

## Core Concepts

### Gradebooks
- One per section-subject-academic year combination
- Contains assessments (tests, quizzes, assignments)
- Three calculation methods:
  - **Average**: Simple average of percentages
  - **Weighted**: Weighted average using assessment weights
  - **Cumulative**: Total points earned / total possible × 100

### Assessments
- Individual grade items within gradebooks
- Automatically create grade records for enrolled students
- Can be included/excluded from final calculations
- Assigned to marking periods

### Grades
- Student scores for specific assessments
- Four statuses: Draft → Pending → Reviewed → Approved
- Only APPROVED grades count in calculations
- Denormalized for performance

### Grade Letters
- School-specific letter grades (A+, A, B+, etc.)
- Configurable percentage ranges
- Validated to prevent overlaps

---

## Grading Modes

The system supports two modes configured at the school level:

### Single Entry Mode

**Best for**: Schools wanting simple, direct grade entry

**How it works**:
- Creates ONE assessment per marking period named "Final Grade"
- Teachers enter final percentages directly
- No detailed breakdown needed

**Configuration**:
```python
# In school settings
grading_style = "single_entry"
single_entry_assessment_type = quiz_type  # What type to use
single_entry_max_points = 100.00  # Max points
```

**Generated Assessments**:
```
MP1: Final Grade (100 points)
MP2: Final Grade (100 points)
MP3: Final Grade (100 points)
MP4: Final Grade (100 points)
```

### Multiple Entry Mode

**Best for**: Schools wanting detailed grade breakdowns

**How it works**:
- Uses assessment templates to define standard assessments
- Templates linked to marking periods via rules
- Generates multiple assessments (quizzes, tests, projects, etc.)

**Configuration**:
```python
# In school settings
grading_style = "multiple_entry"

# Then create templates:
template = DefaultAssessmentTemplate.objects.create(
    school=school,
    name="Quiz 1",
    assessment_type=quiz_type,
    max_score=10,
    weight=1,
    is_active=True
)

# Link to marking periods:
rule = MarkingPeriodAssessmentRule.objects.create(
    marking_period=mp1,
    template=template,
    auto_generate=True
)
```

**Generated Assessments**:
```
MP1: Quiz 1 (10 points), Quiz 2 (10 points), Midterm (50 points)
MP2: Quiz 1 (10 points), Quiz 2 (10 points), Final Exam (100 points)
...
```

---

## Models

### GradeBook
```python
GradeBook(
    section_subject=section_subject,
    academic_year=academic_year,
    name="Math - Grade 10A",
    calculation_method="weighted",  # average, weighted, cumulative
    active=True
)
```

### Assessment
```python
Assessment(
    gradebook=gradebook,
    name="Quiz 1",
    assessment_type=quiz_type,
    marking_period=mp1,
    max_score=10,
    weight=1,
    due_date="2025-10-30",
    is_calculated=True  # Include in final grade?
)
```

### Grade
```python
Grade(
    assessment=assessment,
    student=student,
    score=8.5,
    status="approved",  # draft, pending, reviewed, approved
    notes="Great work!"
)
```

### GradeLetter
```python
GradeLetter(
    school=school,
    letter="A+",
    min_percentage=97.00,
    max_percentage=100.00,
    order=1
)
```

### DefaultAssessmentTemplate (Multiple Entry Mode)
```python
DefaultAssessmentTemplate(
    school=school,
    name="Weekly Quiz",
    assessment_type=quiz_type,
    max_score=10,
    weight=1,
    order=1,
    is_active=True
)
```

### MarkingPeriodAssessmentRule (Multiple Entry Mode)
```python
MarkingPeriodAssessmentRule(
    marking_period=mp1,
    template=template,
    auto_generate=True,
    due_date_offset_days=7  # Due date = MP start + 7 days
)
```

---

## Quick Start

### 1. Configure School Settings

```python
# Via API or admin
POST /api/v1/settings/schools/{school_id}/grading/

{
    "grading_style": "single_entry",  # or "multiple_entry"
    "single_entry_assessment_type": "assessment_type_id",
    "single_entry_max_points": 100.00
}
```

### 2. Set Up Grade Letters

```python
POST /api/v1/grading/schools/{school_id}/grade-letters/

{
    "letter": "A+",
    "min_percentage": 97.00,
    "max_percentage": 100.00,
    "order": 1
}
```

### 3. Set Up Assessment Types

```bash
# Populate default types
python manage.py populate_assessment_types

# Or create custom via API
POST /api/v1/grading/schools/{school_id}/assessment-types/
{
    "name": "Quiz",
    "description": "Short assessments"
}
```

### 4. (Multiple Entry Only) Create Templates

```python
POST /api/v1/grading/schools/{school_id}/default-templates/

{
    "name": "Weekly Quiz",
    "assessment_type": "assessment_type_id",
    "max_score": 10,
    "weight": 1,
    "order": 1
}
```

### 5. (Multiple Entry Only) Create Rules

```python
POST /api/v1/grading/rules/bulk-create/

{
    "template_id": "template_id",
    "marking_period_ids": ["mp1_id", "mp2_id"],
    "auto_generate": true,
    "due_date_offset_days": 7
}
```

### 6. Create Gradebooks

```python
# Assessments auto-generated based on settings!
POST /api/v1/grading/academic-years/{year_id}/gradebooks/

{
    "section_subject": "section_subject_id",
    "name": "Math - Grade 10A",
    "calculation_method": "weighted",
    "auto_generate_assessments": true  # Default is true
}

# Response includes generation results:
{
    "id": "gradebook_id",
    "name": "Math - Grade 10A",
    ...
    "assessment_generation": {
        "mode": "single_entry",
        "assessments_created": 4,
        "assessment_ids": [...],
        "message": "Generated 4 assessments in single_entry mode"
    }
}
```

---

## Configuration

### Settings Location

Grading settings are configured at the school level in the `settings` app:

```python
from settings.models import GradingSettings

settings = GradingSettings.objects.get(school=school)
settings.grading_style  # "single_entry" or "multiple_entry"
settings.single_entry_assessment_type
settings.single_entry_max_points
```

See `settings/docs/` for complete configuration guide.

### Auto-Generation Behavior

| Mode | What Gets Generated | When |
|------|---------------------|------|
| single_entry | 1 "Final Grade" per MP | On gradebook creation (if enabled) |
| multiple_entry | Assessments from templates | On gradebook creation (if enabled) |
| Disabled | Nothing | Teacher adds assessments manually |

Control auto-generation:
```python
# Enable (default)
POST /gradebooks/ {"auto_generate_assessments": true}

# Disable
POST /gradebooks/ {"auto_generate_assessments": false}
```

### Duplicate Prevention

The system NEVER creates duplicate assessments. An assessment is a duplicate if:
1. Same gradebook
2. Same name
3. Same marking period
4. Same assessment type

All 4 must match to be considered a duplicate.

---

## Workflows

### Simple Grading (Single Entry)

```
1. Admin configures school → single_entry mode
2. Create gradebook → System generates "Final Grade" per MP
3. Teacher enters final percentages directly
4. System calculates final grades
```

### Detailed Grading (Multiple Entry)

```
1. Admin configures school → multiple_entry mode
2. Admin creates assessment templates
3. Admin creates marking period rules
4. Create gradebook → System generates assessments from templates
5. Teacher enters scores for each assessment
6. System calculates final grades
```

### Manual Assessment Addition

```
1. Create gradebook (any mode, auto-generation on/off)
2. Teacher manually adds custom assessments
3. Teacher enters grades
4. System calculates or teacher enters final grades
```

### Grade Status Workflow

```
Draft → Pending → Reviewed → Approved
```

Only **APPROVED** grades count in final calculations.

---

## Management Commands

### Initialize Gradebooks (Complete Setup)

**Recommended**: Use this all-in-one command for initial setup or new academic years.

```bash
# Complete initialization (4 steps: types → templates → gradebooks → grades)
python manage.py initialize_gradebooks \
  --school-id <UUID> \
  --academic-year-id <UUID>

# Preview what will be created (safe, no database changes)
python manage.py initialize_gradebooks \
  --school-id <UUID> \
  --academic-year-id <UUID> \
  --dry-run

# Regenerate assessments for existing gradebooks
python manage.py initialize_gradebooks \
  --school-id <UUID> \
  --academic-year-id <UUID> \
  --regenerate

# Skip assessment types (if already populated)
python manage.py initialize_gradebooks \
  --school-id <UUID> \
  --academic-year-id <UUID> \
  --skip-assessment-types

# Skip templates (if already created)
python manage.py initialize_gradebooks \
  --school-id <UUID> \
  --academic-year-id <UUID> \
  --skip-templates
```

**What it does**:
1. **Assessment Types**: Loads from `fixtures/assessment_types.json`
2. **Templates & Rules**: Loads from `fixtures/default_assessments.json`
3. **Gradebooks**: Creates for all section-subjects with auto-generation
4. **Grade Entries**: Pre-creates draft grades for all enrolled students

### Create Gradebooks (Individual Step)

```bash
# Preview (recommended first)
python manage.py create_gradebooks --dry-run

# Create all
python manage.py create_gradebooks

# Specific school
python manage.py create_gradebooks --school-id "school123"

# Specific academic year
python manage.py create_gradebooks --academic-year-id "2024-2025"

# With specific calculation method
python manage.py create_gradebooks --calculation-method weighted
```

### Populate Assessment Types (Individual Step)

```bash
# Preview
python manage.py populate_assessment_types --dry-run

# Populate all schools
python manage.py populate_assessment_types

# Specific school
python manage.py populate_assessment_types --school-id "school123"

# Custom fixture
python manage.py populate_assessment_types --fixture-file "custom.json"
```

### Populate Default Assessments (Individual Step)

```bash
# Preview
python manage.py populate_default_assessments --dry-run

# Populate for school
python manage.py populate_default_assessments --school-id <UUID> --academic-year-id <UUID>

# Overwrite existing templates
python manage.py populate_default_assessments \
  --school-id <UUID> \
  --academic-year-id <UUID> \
  --overwrite

# Skip creating rules (templates only)
python manage.py populate_default_assessments \
  --school-id <UUID> \
  --academic-year-id <UUID> \
  --skip-rules
```

---

## Troubleshooting

### Assessments Not Auto-Generating

**Check:**
1. `auto_generate_assessments` is `true` (default)
2. School has grading settings configured
3. For single_entry: `single_entry_assessment_type` is set
4. For multiple_entry: templates and rules exist
5. Templates are active (`is_active=True`)
6. Rules have `auto_generate=True`

**Debug:**
```python
from settings.models import GradingSettings

settings = GradingSettings.objects.get(school=school)
print(f"Mode: {settings.grading_style}")

if settings.grading_style == 'multiple_entry':
    templates = school.default_assessment_templates.filter(is_active=True)
    print(f"Active templates: {templates.count()}")
```

### Wrong Grading Mode

**Check:**
```python
settings = school.grading_settings
print(f"Grading style: {settings.grading_style}")
```

**Fix:**
```python
# Update via API
PATCH /api/v1/settings/schools/{school_id}/grading/
{
    "grading_style": "single_entry"  # or "multiple_entry"
}
```

### Grades Not Calculating

**Check:**
1. Grades have `status="approved"`
2. Assessments have `is_calculated=True`
3. Student has grades for assessments

**Debug:**
```python
# Check grade statuses
grades = Grade.objects.filter(
    assessment__gradebook=gradebook,
    student=student
)
for g in grades:
    print(f"{g.assessment.name}: {g.score} ({g.status})")
```

### Duplicate Assessments

**This shouldn't happen** - the system prevents duplicates.

If you see duplicates, they differ in at least one of:
- Name
- Marking period
- Assessment type

**Check:**
```python
assessments = Assessment.objects.filter(
    gradebook=gradebook,
    name="Quiz 1"
)
for a in assessments:
    print(f"{a.name} - {a.marking_period} - {a.assessment_type}")
```

---

## Best Practices

### For Schools

1. **Choose Mode Carefully**: Single entry is simpler, multiple entry offers detail
2. **Configure Before Creating Gradebooks**: Set up settings first
3. **Use Templates Wisely**: Create generic templates that apply to all courses
4. **Review Rules**: Ensure marking period rules are correct before generating

### For Developers

1. **Always Use Settings-Aware Functions**: Use `generate_assessments_for_gradebook_with_settings()`
2. **Check School Settings**: Verify grading mode before operations
3. **Handle Both Modes**: Code should work with single_entry and multiple_entry
4. **Use Bulk Operations**: For academic year operations, use bulk endpoints

### For Teachers

1. **Understand Your School's Mode**: Know if you have simple or detailed grading
2. **Use Auto-Generation**: Let the system create assessments when possible
3. **Approve Grades**: Remember to approve grades for them to count
4. **Check Calculations**: Verify final grades match your calculation method

---

## Database Schema

```
School
├── GradingSettings (school-level configuration)
├── GradeLetter (grading scale)
├── AssessmentType (Quiz, Test, etc.)
├── DefaultAssessmentTemplate (for multiple_entry mode)
│
├── AcademicYear
│   ├── MarkingPeriod
│   │   └── MarkingPeriodAssessmentRule (links templates to periods)
│   │
│   └── GradeBook
│       └── Assessment
│           └── Grade (student scores)
│
└── Section
    ├── SectionSubject (links section to subject)
    └── Enrollment (students in section)
```

**Key Constraints**:
- One gradebook per `(section_subject, academic_year, name)`
- One grade letter per `(school, letter)`
- Grade letter ranges cannot overlap
- Assessment types unique per school

---

## Related Documentation

- **[API_REFERENCE.md](./API_REFERENCE.md)** - Complete API documentation
- **[DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md)** - Technical implementation details
- **Settings Docs** - `settings/docs/` - Grading settings configuration

---

## Version

- **Current**: v2.1
- **Last Update**: October 24, 2025
- **Status**: Production Ready

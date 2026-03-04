# Developer Guide

Technical documentation for developers working on the grading system.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Settings Integration](#settings-integration)
3. [Assessment Generation](#assessment-generation)
4. [Calculation Engine](#calculation-engine)
5. [Serializers](#serializers)
6. [Permissions](#permissions)
7. [Performance](#performance)
8. [Testing](#testing)
9. [Database Schema](#database-schema)

---

## Architecture Overview

### Design Principles

- **Settings-Driven**: All behavior configurable via School settings
- **Mode Separation**: Clear distinction between single_entry and multiple_entry modes
- **Template-Based**: Reusable templates for common assessments
- **Calculation Agnostic**: Support multiple calculation methods
- **Audit Trail**: Full history tracking for grades

### Core Layers

```
┌─────────────────────────────────────────┐
│          Views / API Endpoints          │
├─────────────────────────────────────────┤
│            Serializers                  │
├─────────────────────────────────────────┤
│          Business Logic                 │
│  (Generation, Calculation, Rules)       │
├─────────────────────────────────────────┤
│             Models                      │
├─────────────────────────────────────────┤
│            Database                     │
└─────────────────────────────────────────┘
```

---

## Settings Integration

### School-Level Configuration

**Location**: `core.models.School.settings['grading']`

```python
{
  "grading_style": "single_entry",  # or "multiple_entry"
  "calculation_method": "weighted",  # or "average", "cumulative"
  "allow_extra_credit": true,
  "passing_grade": 60.0
}
```

### Accessing Settings

```python
from grading.utils.settings import get_grading_style, get_calculation_method

# Get grading style for a school
style = get_grading_style(school)  # Returns: "single_entry" | "multiple_entry"

# Get calculation method
method = get_calculation_method(school)  # Returns: "weighted" | "average" | "cumulative"
```

### Settings-Aware Functions

All generation functions now check settings:

```python
from grading.utils.generation import (
    generate_assessments_for_gradebook_with_settings,
    create_gradebook_with_assessments
)

# Auto-detects grading mode from school settings
assessments = generate_assessments_for_gradebook_with_settings(gradebook)

# Convenience wrapper for creation + generation
gradebook = create_gradebook_with_assessments(
    section_subject=section_subject,
    academic_year=academic_year,
    auto_generate=True  # Respects school grading_style
)
```

---

## Assessment Generation

### Generation Modes

#### Single Entry Mode

**Purpose**: One "Final Grade" assessment per marking period.

**Function**: `generate_single_entry_assessments()`

```python
def generate_single_entry_assessments(gradebook):
    """
    Generate one assessment per marking period.
    
    Args:
        gradebook: Gradebook instance
    
    Returns:
        list: Created Assessment instances
    """
    assessments = []
    marking_periods = gradebook.academic_year.marking_periods.all()
    
    for mp in marking_periods:
        assessment = Assessment.objects.create(
            gradebook=gradebook,
            name=f"Final Grade - {mp.name}",
            marking_period=mp,
            max_score=100.00,
            weight=1.0,
            is_calculated=True
        )
        assessments.append(assessment)
    
    return assessments
```

**Use Cases**:
- Traditional report card grading
- Simple course structures
- Elementary/middle school
- Minimal teacher overhead

#### Multiple Entry Mode

**Purpose**: Template-based multiple assessments per marking period.

**Function**: `generate_assessments_from_templates()`

```python
def generate_assessments_from_templates(gradebook, regenerate=False):
    """
    Generate assessments based on templates and marking period rules.
    
    Args:
        gradebook: Gradebook instance
        regenerate: If True, delete existing and recreate
    
    Returns:
        dict: {
            'created': int,
            'skipped': int,
            'assessments': list
        }
    """
    from grading.defaults.utils import generate_default_assessments_for_gradebook
    
    return generate_default_assessments_for_gradebook(gradebook, regenerate)
```

**Logic Flow**:

```
1. Get all marking periods for academic year
   ↓
2. For each marking period:
   - Find applicable rules (MarkingPeriodRule)
   - Filter by auto_generate=True
   ↓
3. For each rule:
   - Get associated template
   - Check if assessment already exists
   ↓
4. Create assessment:
   - Copy template attributes
   - Set gradebook and marking period
   - Calculate due date (offset from MP end)
   ↓
5. Return creation summary
```

**Use Cases**:
- High school/college
- Multiple graded components
- Standardized assessment structure
- Detailed progress tracking

### Settings-Aware Generation

**Main Function**: `generate_assessments_for_gradebook_with_settings()`

```python
def generate_assessments_for_gradebook_with_settings(gradebook, regenerate=False):
    """
    Generate assessments respecting school grading_style setting.
    
    Automatically chooses:
    - single_entry → generate_single_entry_assessments()
    - multiple_entry → generate_assessments_from_templates()
    
    Args:
        gradebook: Gradebook instance
        regenerate: Only applies to multiple_entry mode
    
    Returns:
        dict: {
            'mode': str,
            'assessments': list,
            'count': int
        }
    """
    from grading.utils.settings import get_grading_style
    
    style = get_grading_style(gradebook.section_subject.section.school)
    
    if style == "single_entry":
        assessments = generate_single_entry_assessments(gradebook)
        return {
            'mode': 'single_entry',
            'assessments': assessments,
            'count': len(assessments)
        }
    else:
        result = generate_assessments_from_templates(gradebook, regenerate)
        return {
            'mode': 'multiple_entry',
            'assessments': result['assessments'],
            'count': result['created']
        }
```

### Bulk Generation

**For Academic Year**: `generate_default_assessments_for_academic_year()`

```python
def generate_default_assessments_for_academic_year(academic_year, regenerate=False):
    """
    Generate assessments for all gradebooks in academic year.
    
    Processes each gradebook based on its school's grading_style.
    Provides detailed results including error tracking.
    
    Args:
        academic_year: AcademicYear instance
        regenerate: Whether to delete and recreate assessments
    
    Returns:
        dict: {
            'gradebooks_processed': int,
            'assessments_created': int,
            'single_entry_gradebooks': int,
            'multiple_entry_gradebooks': int,
            'gradebooks_with_errors': list,
            'error_count': int
        }
    """
    results = {
        'gradebooks_processed': 0,
        'assessments_created': 0,
        'single_entry_gradebooks': 0,
        'multiple_entry_gradebooks': 0,
        'gradebooks_with_errors': [],
        'error_count': 0
    }
    
    gradebooks = Gradebook.objects.filter(
        academic_year=academic_year,
        active=True
    ).select_related('section_subject__section__school')
    
    for gradebook in gradebooks:
        try:
            result = generate_assessments_for_gradebook_with_settings(
                gradebook,
                regenerate=regenerate
            )
            
            results['gradebooks_processed'] += 1
            results['assessments_created'] += result['count']
            
            if result['mode'] == 'single_entry':
                results['single_entry_gradebooks'] += 1
            else:
                results['multiple_entry_gradebooks'] += 1
                
        except Exception as e:
            results['gradebooks_with_errors'].append({
                'gradebook_id': str(gradebook.id),
                'error': str(e)
            })
            results['error_count'] += 1
    
    return results
```

### Auto-Generation on Create

**Serializer Integration**:

```python
class GradebookSerializer(serializers.ModelSerializer):
    auto_generate_assessments = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False
    )
    assessment_generation = serializers.SerializerMethodField(read_only=True)
    
    def create(self, validated_data):
        auto_generate = validated_data.pop('auto_generate_assessments', False)
        gradebook = super().create(validated_data)
        
        if auto_generate:
            result = generate_assessments_for_gradebook_with_settings(gradebook)
            gradebook._assessment_generation = result
        
        return gradebook
    
    def get_assessment_generation(self, obj):
        if hasattr(obj, '_assessment_generation'):
            return {
                'mode': obj._assessment_generation['mode'],
                'assessments_created': obj._assessment_generation['count'],
                'assessment_ids': [str(a.id) for a in obj._assessment_generation['assessments']],
                'message': f"Generated {obj._assessment_generation['count']} assessments in {obj._assessment_generation['mode']} mode"
            }
        return None
```

---

## Calculation Engine

### Calculation Methods

#### Average Method

```python
def calculate_average_grade(assessments, grades):
    """
    Simple average: sum(scores) / sum(max_scores)
    """
    total_earned = sum(g.score for g in grades if g.score is not None)
    total_possible = sum(a.max_score for a in assessments)
    
    return (total_earned / total_possible * 100) if total_possible > 0 else 0
```

#### Weighted Method

```python
def calculate_weighted_grade(assessments, grades):
    """
    Weighted: sum(score * weight) / sum(max_score * weight)
    """
    weighted_earned = 0
    weighted_possible = 0
    
    for assessment in assessments:
        grade = next((g for g in grades if g.assessment_id == assessment.id), None)
        if grade and grade.score is not None:
            weighted_earned += grade.score * assessment.weight
            weighted_possible += assessment.max_score * assessment.weight
    
    return (weighted_earned / weighted_possible * 100) if weighted_possible > 0 else 0
```

#### Cumulative Method

```python
def calculate_cumulative_grade(assessments, grades):
    """
    Cumulative: sum of all points earned / sum of all points possible
    """
    points_earned = sum(g.score for g in grades if g.score is not None)
    points_possible = sum(a.max_score for a in assessments)
    
    return (points_earned / points_possible * 100) if points_possible > 0 else 0
```

### Final Grade Calculation

**View**: `FinalGradeView`

```python
class FinalGradeView(APIView):
    def get(self, request):
        student_id = request.query_params.get('student_id')
        gradebook_id = request.query_params.get('gradebook_id')
        marking_period_id = request.query_params.get('marking_period_id')
        include_pending = request.query_params.get('include_pending', 'false').lower() == 'true'
        
        # Get gradebook
        gradebook = get_object_or_404(Gradebook, id=gradebook_id)
        
        # Build query
        assessment_qs = Assessment.objects.filter(
            gradebook=gradebook,
            is_calculated=True
        )
        
        if marking_period_id:
            assessment_qs = assessment_qs.filter(marking_period_id=marking_period_id)
        
        assessments = list(assessment_qs)
        
        # Get grades
        grade_qs = Grade.objects.filter(
            assessment__in=assessments,
            student_id=student_id
        )
        
        if not include_pending:
            grade_qs = grade_qs.filter(status='approved')
        
        grades = list(grade_qs)
        
        # Calculate based on method
        method = gradebook.calculation_method
        if method == 'weighted':
            percentage = calculate_weighted_grade(assessments, grades)
        elif method == 'cumulative':
            percentage = calculate_cumulative_grade(assessments, grades)
        else:  # average
            percentage = calculate_average_grade(assessments, grades)
        
        # Get letter grade
        letter_grade = get_letter_grade(percentage, gradebook.section_subject.section.school)
        
        return Response({
            'final_percentage': round(percentage, 2),
            'letter_grade': letter_grade,
            'calculation_method': method,
            'assessments': [...],
            'total_points_earned': sum(g.score for g in grades if g.score),
            'total_points_possible': sum(a.max_score for a in assessments)
        })
```

---

## Serializers

### Nested Relationships

**Pattern**: Use `SerializerMethodField` for read-only nesting, separate serializers for write:

```python
class GradebookSerializer(serializers.ModelSerializer):
    # Read: Full nested objects
    section_subject = SectionSubjectSerializer(read_only=True)
    academic_year = AcademicYearSerializer(read_only=True)
    
    # Write: Accept UUIDs
    section_subject_id = serializers.UUIDField(write_only=True)
    academic_year_id = serializers.UUIDField(write_only=True)
    
    class Meta:
        model = Gradebook
        fields = [
            'id', 'section_subject', 'section_subject_id',
            'academic_year', 'academic_year_id',
            'name', 'calculation_method', 'active'
        ]
```

### Assessment Generation Field

**Dynamic Field**: Only populated when auto-generation occurs:

```python
assessment_generation = serializers.SerializerMethodField(read_only=True)

def get_assessment_generation(self, obj):
    # Only returns data if _assessment_generation attribute exists
    if hasattr(obj, '_assessment_generation'):
        return {
            'mode': obj._assessment_generation['mode'],
            'assessments_created': obj._assessment_generation['count'],
            'assessment_ids': [str(a.id) for a in obj._assessment_generation['assessments']],
            'message': f"Generated {obj._assessment_generation['count']} assessments"
        }
    return None
```

### Performance Optimization

**Select Related**: Reduce queries with prefetching:

```python
class AssessmentViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        return Assessment.objects.select_related(
            'gradebook',
            'gradebook__section_subject',
            'gradebook__section_subject__section',
            'gradebook__section_subject__section__school',
            'marking_period',
            'assessment_type'
        ).prefetch_related('grades')
```

---

## Permissions

### Custom Permission Classes

**IsTeacherOfSection**: Teacher can only access their assigned sections

```python
class IsTeacherOfSection(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.role != 'teacher':
            return False
        
        # Get section from different objects
        if isinstance(obj, Gradebook):
            section = obj.section_subject.section
        elif isinstance(obj, Assessment):
            section = obj.gradebook.section_subject.section
        elif isinstance(obj, Grade):
            section = obj.assessment.gradebook.section_subject.section
        else:
            return False
        
        # Check if teacher is assigned to section
        return section.teachers.filter(id=request.user.id).exists()
```

**CanApproveGrades**: Only admins can approve grades

```python
class CanApproveGrades(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in ['PATCH', 'PUT']:
            if 'status' in request.data and request.data['status'] == 'approved':
                return request.user.role == 'admin'
        return True
```

### View-Level Permissions

```python
class GradeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsTeacherOfSection | IsAdmin]
    
    def get_permissions(self):
        if self.action in ['approve', 'bulk_approve']:
            return [IsAuthenticated(), CanApproveGrades()]
        return super().get_permissions()
```

---

## Performance

### Query Optimization

**Problem**: N+1 queries when listing gradebooks with related data

**Solution**: Use `select_related` and `prefetch_related`

```python
# Bad (N+1 queries)
gradebooks = Gradebook.objects.all()
for gb in gradebooks:
    print(gb.section_subject.section.name)  # Query per gradebook!

# Good (2 queries)
gradebooks = Gradebook.objects.select_related(
    'section_subject__section',
    'academic_year'
).all()
for gb in gradebooks:
    print(gb.section_subject.section.name)  # No additional queries
```

### Bulk Operations

**Bulk Grade Creation**:

```python
def bulk_create_grades(assessment, student_ids, default_score=None):
    """
    Create grades for multiple students efficiently.
    """
    grades = [
        Grade(
            assessment=assessment,
            student_id=student_id,
            score=default_score,
            status='draft'
        )
        for student_id in student_ids
    ]
    
    return Grade.objects.bulk_create(grades, ignore_conflicts=True)
```

### Caching

**Cache Frequently Accessed Settings**:

```python
from django.core.cache import cache

def get_grading_style(school):
    cache_key = f'grading_style_{school.id}'
    style = cache.get(cache_key)
    
    if style is None:
        style = school.settings.get('grading', {}).get('grading_style', 'single_entry')
        cache.set(cache_key, style, timeout=3600)  # Cache for 1 hour
    
    return style
```

---

## Testing

### Test Structure

```
tests/
├── test_models.py           # Model validation, constraints
├── test_serializers.py      # Serializer validation
├── test_views.py            # API endpoint tests
├── test_generation.py       # Assessment generation logic
├── test_calculation.py      # Grade calculation methods
└── test_permissions.py      # Permission checks
```

### Sample Test Cases

**Test Assessment Generation**:

```python
class AssessmentGenerationTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Test School")
        self.academic_year = AcademicYear.objects.create(
            school=self.school,
            year="2024-2025"
        )
        self.section = Section.objects.create(
            school=self.school,
            name="Grade 10A"
        )
        self.section_subject = SectionSubject.objects.create(
            section=self.section,
            subject=Subject.objects.create(name="Math")
        )
    
    def test_single_entry_generation(self):
        """Test single entry mode generates one assessment per marking period"""
        self.school.settings = {'grading': {'grading_style': 'single_entry'}}
        self.school.save()
        
        gradebook = Gradebook.objects.create(
            section_subject=self.section_subject,
            academic_year=self.academic_year,
            name="Math Gradebook"
        )
        
        result = generate_assessments_for_gradebook_with_settings(gradebook)
        
        self.assertEqual(result['mode'], 'single_entry')
        self.assertEqual(result['count'], 4)  # 4 marking periods
        self.assertTrue(all(a.name.startswith('Final Grade') for a in result['assessments']))
    
    def test_multiple_entry_generation(self):
        """Test multiple entry mode generates from templates"""
        self.school.settings = {'grading': {'grading_style': 'multiple_entry'}}
        self.school.save()
        
        # Create templates and rules...
        
        gradebook = Gradebook.objects.create(
            section_subject=self.section_subject,
            academic_year=self.academic_year,
            name="Math Gradebook"
        )
        
        result = generate_assessments_for_gradebook_with_settings(gradebook)
        
        self.assertEqual(result['mode'], 'multiple_entry')
        self.assertGreater(result['count'], 4)  # More than just final grades
```

**Test API Endpoints**:

```python
class GradebookAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='teacher',
            password='testpass',
            role='teacher'
        )
        self.client.force_authenticate(user=self.user)
    
    def test_create_gradebook_with_auto_generation(self):
        """Test POST with auto_generate_assessments=True"""
        url = reverse('gradebook-list', args=[self.academic_year.id])
        data = {
            'section_subject': str(self.section_subject.id),
            'name': 'Test Gradebook',
            'calculation_method': 'weighted',
            'auto_generate_assessments': True
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, 201)
        self.assertIn('assessment_generation', response.data)
        self.assertGreater(response.data['assessment_generation']['assessments_created'], 0)
```

### Running Tests

```bash
# Run all grading tests
python manage.py test grading

# Run specific test file
python manage.py test grading.tests.test_generation

# Run with coverage
coverage run --source='grading' manage.py test grading
coverage report
```

---

## Database Schema

### Core Models Diagram

```
┌─────────────────┐
│     School      │
│ ─────────────── │
│ id (UUID)       │
│ name            │
│ settings (JSON) │
└────────┬────────┘
         │
         ├──────────────────────────────┐
         │                              │
         ▼                              ▼
┌─────────────────┐            ┌─────────────────┐
│  AcademicYear   │            │    Section      │
│ ─────────────── │            │ ─────────────── │
│ id (UUID)       │            │ id (UUID)       │
│ school_id (FK)  │            │ school_id (FK)  │
│ year            │            │ name            │
└────────┬────────┘            └────────┬────────┘
         │                              │
         │                              │
         ▼                              ▼
┌─────────────────┐            ┌─────────────────┐
│ MarkingPeriod   │            │ SectionSubject  │
│ ─────────────── │            │ ─────────────── │
│ id (UUID)       │            │ id (UUID)       │
│ academic_year   │            │ section_id (FK) │
│ name            │            │ subject_id (FK) │
│ start_date      │            └────────┬────────┘
│ end_date        │                     │
└─────────────────┘                     │
                                        │
         ┌──────────────────────────────┘
         │
         ▼
┌─────────────────┐
│   Gradebook     │
│ ─────────────── │
│ id (UUID)       │
│ section_subj_id │
│ academic_year_id│
│ name            │
│ calc_method     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Assessment    │
│ ─────────────── │
│ id (UUID)       │
│ gradebook_id    │
│ marking_pd_id   │
│ name            │
│ max_score       │
│ weight          │
│ is_calculated   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│     Grade       │
│ ─────────────── │
│ id (UUID)       │
│ assessment_id   │
│ student_id      │
│ score           │
│ status          │
└─────────────────┘
```

### Template System (Multiple Entry Mode)

```
┌─────────────────┐
│DefaultTemplate  │
│ ─────────────── │
│ id (UUID)       │
│ school_id (FK)  │
│ name            │
│ max_score       │
│ weight          │
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│MarkingPeriodRule   │
│ ─────────────────── │
│ id (UUID)           │
│ template_id (FK)    │
│ marking_period_id   │
│ auto_generate (bool)│
└─────────────────────┘
```

### Indexes

```sql
-- Gradebook lookups
CREATE INDEX idx_gradebook_section_subject ON grading_gradebook(section_subject_id);
CREATE INDEX idx_gradebook_academic_year ON grading_gradebook(academic_year_id);

-- Assessment queries
CREATE INDEX idx_assessment_gradebook ON grading_assessment(gradebook_id);
CREATE INDEX idx_assessment_marking_period ON grading_assessment(marking_period_id);

-- Grade lookups (most critical)
CREATE INDEX idx_grade_assessment ON grading_grade(assessment_id);
CREATE INDEX idx_grade_student ON grading_grade(student_id);
CREATE INDEX idx_grade_status ON grading_grade(status);
CREATE INDEX idx_grade_assessment_student ON grading_grade(assessment_id, student_id);
```

---

## Best Practices

### 1. Always Check Settings

Before any generation or calculation:

```python
from grading.utils.settings import get_grading_style

style = get_grading_style(school)
if style == "single_entry":
    # Handle single entry logic
else:
    # Handle multiple entry logic
```

### 2. Use Transactions for Bulk Operations

```python
from django.db import transaction

@transaction.atomic
def create_gradebook_with_assessments(section_subject, academic_year):
    gradebook = Gradebook.objects.create(...)
    assessments = generate_assessments_for_gradebook_with_settings(gradebook)
    return gradebook
```

### 3. Validate Before Delete

```python
def delete_assessment(assessment_id):
    assessment = Assessment.objects.get(id=assessment_id)
    
    # Check if grades exist
    if assessment.grades.exists():
        raise ValidationError("Cannot delete assessment with existing grades")
    
    assessment.delete()
```

### 4. Use Serializer Validation

```python
class GradebookSerializer(serializers.ModelSerializer):
    def validate(self, data):
        # Check for duplicate
        if Gradebook.objects.filter(
            section_subject=data['section_subject'],
            academic_year=data['academic_year'],
            name=data['name']
        ).exists():
            raise ValidationError("Gradebook with this name already exists")
        
        return data
```

### 5. Log Important Operations

```python
import logging

logger = logging.getLogger(__name__)

def generate_assessments_for_academic_year(academic_year):
    logger.info(f"Starting assessment generation for {academic_year}")
    
    result = generate_default_assessments_for_academic_year(academic_year)
    
    logger.info(
        f"Completed: {result['assessments_created']} assessments created "
        f"across {result['gradebooks_processed']} gradebooks"
    )
    
    if result['error_count'] > 0:
        logger.error(f"Errors: {result['gradebooks_with_errors']}")
    
    return result
```

---

## Migration Guide

### Adding New Calculation Method

1. **Add to Model Choices**:
```python
CALCULATION_METHOD_CHOICES = [
    ('average', 'Average'),
    ('weighted', 'Weighted'),
    ('cumulative', 'Cumulative'),
    ('custom', 'Custom'),  # New method
]
```

2. **Implement Calculation Function**:
```python
def calculate_custom_grade(assessments, grades):
    # Your custom logic
    pass
```

3. **Update FinalGradeView**:
```python
if method == 'custom':
    percentage = calculate_custom_grade(assessments, grades)
```

4. **Add Tests**:
```python
def test_custom_calculation():
    # Test custom method
    pass
```

### Adding New Grading Mode

1. **Update Settings Schema**
2. **Create Generation Function**
3. **Update `generate_assessments_for_gradebook_with_settings()`**
4. **Add Serializer Support**
5. **Document in GRADING_GUIDE.md**

---

## Troubleshooting

### Common Issues

**Issue**: Assessments not generating
```python
# Check school settings
school = School.objects.get(id=school_id)
print(school.settings.get('grading', {}))

# Check marking periods exist
print(academic_year.marking_periods.count())

# Check templates and rules (multiple_entry mode)
print(school.default_templates.count())
```

**Issue**: Calculation returns 0
```python
# Check is_calculated flag
print(assessment.is_calculated)

# Check grade statuses
print(grade.status)  # Must be 'approved' unless include_pending=True

# Check for null scores
print([g for g in grades if g.score is None])
```

**Issue**: Permission denied
```python
# Check user role
print(request.user.role)

# Check section assignment (teachers)
print(section.teachers.filter(id=user.id).exists())
```

---

## Additional Resources

- **Django Docs**: https://docs.djangoproject.com/
- **DRF Docs**: https://www.django-rest-framework.org/
- **Project README**: `../README.md`
- **API Reference**: `./API_REFERENCE.md`
- **User Guide**: `./GRADING_GUIDE.md`

# Grading API Reference

Complete API documentation for the grading system.

---

## Base URL

```
/api/v1/grading/
```

All endpoints require authentication via Bearer token:
```
Authorization: Bearer {your_jwt_token}
```

---

## Pagination

All list endpoints support pagination:

| Parameter | Description | Default | Range |
|-----------|-------------|---------|-------|
| `page` | Page number (1-based) | 1 | 1+ |
| `page_size` | Items per page | 50 | 1-200 |

**Response Format**:
```json
{
  "meta": {
    "count": 150,
    "page": 2,
    "page_size": 25,
    "total_pages": 6,
    "has_next": true,
    "has_previous": true
  },
  "results": [...]
}
```

---

## Gradebooks

### List/Create Gradebooks

```http
GET /academic-years/{academic_year_id}/gradebooks/
POST /academic-years/{academic_year_id}/gradebooks/
```

**Query Parameters** (GET):
- `page`, `page_size`: Pagination
- `section_id`: Filter by section
- `section_subject`: Filter by section subject
- `calculation_method`: Filter by method

**Request Body** (POST):
```json
{
  "section_subject": "uuid",
  "name": "Math - Grade 10A",
  "calculation_method": "weighted",
  "auto_generate_assessments": true
}
```

**Response** (POST with auto-generation):
```json
{
  "id": "uuid",
  "section_subject": {...},
  "academic_year": {...},
  "name": "Math - Grade 10A",
  "calculation_method": "weighted",
  "active": true,
  "assessment_generation": {
    "mode": "single_entry",
    "assessments_created": 4,
    "assessment_ids": ["uuid1", "uuid2", "uuid3", "uuid4"],
    "message": "Generated 4 assessments in single_entry mode"
  }
}
```

### Get/Update/Delete Gradebook

```http
GET /gradebooks/{id}/
PATCH /gradebooks/{id}/
DELETE /gradebooks/{id}/
```

**Request Body** (PATCH):
```json
{
  "name": "Updated Name",
  "calculation_method": "average"
}
```

---

## Assessment Generation

### Generate for Single Gradebook

```http
POST /gradebooks/{id}/generate-assessments/
```

**Request Body**:
```json
{
  "dry_run": false
}
```

**Response**:
```json
{
  "mode": "multiple_entry",
  "assessments_created": 12,
  "assessment_ids": ["uuid1", "uuid2", ...],
  "message": "Generated 12 assessments in multiple_entry mode"
}
```

### Bulk Generate for Academic Year

```http
POST /academic-years/{id}/generate-assessments/
```

**Request Body**:
```json
{
  "regenerate": false
}
```

**Response**:
```json
{
  "gradebooks_processed": 25,
  "assessments_created": 85,
  "single_entry_gradebooks": 10,
  "multiple_entry_gradebooks": 15,
  "gradebooks_with_errors": [],
  "success": true,
  "error_count": 0
}
```

---

## Assessments

### List/Create Assessments

```http
GET /gradebooks/{gradebook_id}/assessments/
POST /gradebooks/{gradebook_id}/assessments/
```

**Query Parameters** (GET):
- `page`, `page_size`: Pagination
- `marking_period`: Filter by marking period (required)
- `assessment_type`: Filter by type
- `is_calculated`: Filter by calculation inclusion

**Request Body** (POST):
```json
{
  "name": "Midterm Exam",
  "assessment_type": "uuid",
  "marking_period": "uuid",
  "max_score": 100.00,
  "weight": 2.0,
  "due_date": "2025-11-15",
  "is_calculated": true,
  "description": "Chapters 1-5"
}
```

### Get/Update/Delete Assessment

```http
GET /assessments/{id}/
PATCH /assessments/{id}/
DELETE /assessments/{id}/
```

---

## Grades

### List/Create Grades

```http
GET /assessments/{assessment_id}/grades/
POST /assessments/{assessment_id}/grades/
```

**Query Parameters** (GET):
- `page`, `page_size`: Pagination
- `student_id`: Filter by student
- `status`: Filter by status
- `section_id`: Filter by section

**Request Body** (POST):
```json
{
  "student": "uuid",
  "score": 85.5,
  "status": "draft",
  "notes": "Good improvement"
}
```

### Get/Update Grade

```http
GET /grades/{id}/
PATCH /grades/{id}/
```

**Request Body** (PATCH):
```json
{
  "score": 90.0,
  "status": "approved",
  "notes": "Excellent work"
}
```

### Bulk Status Update

```http
POST /sections/{section_id}/grades/status/
```

**Request Body**:
```json
{
  "status": "approved",
  "assessment_ids": ["uuid1", "uuid2"],
  "marking_period_id": "uuid"
}
```

---

## Final Grades

### Calculate Final Grade

```http
GET /final-grade/
```

**Query Parameters**:
- `student_id`: Required
- `gradebook_id`: Required
- `marking_period_id`: Optional
- `include_pending`: Include non-approved grades (default: false)

**Response**:
```json
{
  "student": {
    "id": "uuid",
    "name": "John Doe"
  },
  "gradebook": {
    "id": "uuid",
    "name": "Mathematics - Grade 10A"
  },
  "final_percentage": 87.5,
  "letter_grade": "B+",
  "calculation_method": "weighted",
  "assessments": [
    {
      "name": "Quiz 1",
      "score": 85.0,
      "max_score": 100.0,
      "weight": 1.0,
      "percentage": 85.0
    }
  ],
  "total_points_earned": 175.0,
  "total_points_possible": 200.0
}
```

### Student Final Grades

```http
GET /students/{student_id}/final-grades/
GET /students/{student_id}/final-grades/gradebook/{gradebook_id}/
```

### Section Final Grades

```http
GET /sections/{section_id}/final-grades/
GET /sections/{section_id}/final-grades/subject/{subject_id}/
```

---

## Grade Letters

### List/Create Grade Letters

```http
GET /schools/{school_id}/grade-letters/
POST /schools/{school_id}/grade-letters/
```

**Request Body** (POST):
```json
{
  "letter": "A+",
  "min_percentage": 97.00,
  "max_percentage": 100.00,
  "order": 1
}
```

### Get/Update/Delete Grade Letter

```http
GET /grade-letters/{id}/
PATCH /grade-letters/{id}/
DELETE /grade-letters/{id}/
```

---

## Assessment Types

### List/Create Assessment Types

```http
GET /schools/{school_id}/assessment-types/
POST /schools/{school_id}/assessment-types/
```

**Query Parameters** (GET):
- `page`, `page_size`: Pagination
- `active`: Filter by active status

**Request Body** (POST):
```json
{
  "name": "Quiz",
  "description": "Short assessments covering recent topics"
}
```

### Get/Update/Delete Assessment Type

```http
GET /assessment-types/{id}/
PATCH /assessment-types/{id}/
DELETE /assessment-types/{id}/
```

---

## Templates (Multiple Entry Mode)

### List/Create Templates

```http
GET /schools/{school_id}/default-templates/
POST /schools/{school_id}/default-templates/
```

**Request Body** (POST):
```json
{
  "name": "Weekly Quiz",
  "assessment_type": "uuid",
  "max_score": 10,
  "weight": 1,
  "is_calculated": true,
  "order": 1,
  "description": "Weekly comprehension check"
}
```

### Get/Update/Delete Template

```http
GET /default-templates/{id}/
PATCH /default-templates/{id}/
DELETE /default-templates/{id}/
```

---

## Marking Period Rules (Multiple Entry Mode)

### List/Create Rules

```http
GET /marking-periods/{marking_period_id}/rules/
POST /marking-periods/{marking_period_id}/rules/
```

**Request Body** (POST):
```json
{
  "template": "uuid",
  "auto_generate": true,
  "due_date_offset_days": 7,
  "allowed_assessment_types": ["uuid1", "uuid2"]
}
```

### Bulk Create Rules

```http
POST /rules/bulk-create/
```

**Request Body**:
```json
{
  "template_id": "uuid",
  "marking_period_ids": ["uuid1", "uuid2", "uuid3"],
  "auto_generate": true,
  "due_date_offset_days": 7
}
```

### Get/Update/Delete Rule

```http
GET /rules/{id}/
PATCH /rules/{id}/
DELETE /rules/{id}/
```

---

## Error Responses

### Standard HTTP Status Codes

- `200`: Success
- `201`: Created
- `400`: Bad Request (validation errors)
- `401`: Unauthorized
- `403`: Forbidden
- `404`: Not Found
- `500`: Internal Server Error

### Error Format

```json
{
  "detail": "Error message",
  "errors": {
    "field_name": ["Error for this field"]
  }
}
```

### Common Errors

**Duplicate Gradebook**:
```json
{
  "detail": "Gradebook with this name already exists for this section-subject and academic year."
}
```

**Invalid Calculation Method**:
```json
{
  "detail": "Invalid calculation_method. Must be: average, weighted, or cumulative"
}
```

**Grade Letter Overlap**:
```json
{
  "detail": "Grade letter ranges cannot overlap.",
  "errors": {
    "min_percentage": ["Overlaps with existing grade letter A"]
  }
}
```

---

## Permissions

### By Role

| Endpoint | Teacher | Admin | Student | Parent |
|----------|---------|-------|---------|--------|
| View Gradebooks | Assigned sections | All | Own | Children |
| Create Gradebooks | No | Yes | No | No |
| View Assessments | Assigned sections | All | Own | Children |
| Create Assessments | Assigned sections | All | No | No |
| View Grades | Assigned sections | All | Own | Children |
| Enter Grades | Assigned sections | All | No | No |
| Approve Grades | No | Yes | No | No |
| Configure Settings | No | Yes | No | No |

---

## Rate Limiting

- **Standard**: 100 requests per minute
- **Bulk Operations**: 10 requests per minute

Exceed limits:
```json
{
  "detail": "Rate limit exceeded. Try again in 30 seconds."
}
```

---

## Examples

### Complete Workflow: Create Gradebook with Auto-Generation

```bash
# 1. Create gradebook (assessments auto-generated)
curl -X POST /api/v1/grading/academic-years/{year_id}/gradebooks/ \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "section_subject": "uuid",
    "name": "Math - Grade 10A",
    "calculation_method": "weighted",
    "auto_generate_assessments": true
  }'

# Response includes assessment_generation with created assessments

# 2. Get assessments for marking period
curl -X GET /api/v1/grading/gradebooks/{id}/assessments/?marking_period={mp_id} \
  -H "Authorization: Bearer {token}"

# 3. Enter grades
curl -X POST /api/v1/grading/assessments/{assessment_id}/grades/ \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "student": "student_uuid",
    "score": 85.5,
    "status": "draft"
  }'

# 4. Approve grades
curl -X PATCH /api/v1/grading/grades/{grade_id}/ \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"status": "approved"}'

# 5. Get final grade
curl -X GET "/api/v1/grading/final-grade/?student_id={student_id}&gradebook_id={gradebook_id}" \
  -H "Authorization: Bearer {token}"
```

---

## Webhooks (Future)

Coming soon: Webhook support for grade updates and approval notifications.

---

## SDK Support (Future)

Coming soon: JavaScript and Python SDKs for easier integration.

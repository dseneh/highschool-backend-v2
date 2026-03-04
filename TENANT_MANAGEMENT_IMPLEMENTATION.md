# Tenant Management Implementation Summary

## Overview
Complete implementation of multi-tenant architecture improvements including:
- Automatic tenant schema creation and default data population
- Tenant user listing endpoint
- String-based user account references instead of cross-schema FKs
- Fixed model references (School → Tenant, CustomUser → User)

## 1. Automatic Tenant Creation & Default Data

### Schema Auto-Creation
**Location:** `core/models.py` - Tenant model

The Tenant model has `auto_create_schema = True`, which automatically creates a PostgreSQL schema when a new tenant is created. This is handled by django-tenants.

```python
class Tenant(TenantBase):
    # ... fields ...
    
    # Automatically create schema when tenant is created
    auto_create_schema = True
    # Don't auto-drop schema on delete (safety)
    auto_drop_schema = False
```

### Default Data Population
**Location:** `core/serializers.py` - CreateTenantSerializer.create()

When a tenant is created via the API, the `CreateTenantSerializer.create()` method automatically:

1. **Creates the tenant** with all profile information
2. **Creates the primary domain** for routing
3. **Adds the owner as superuser** to the tenant schema
4. **Adds all superadmin users** to the tenant (for global admin access)
5. **Initializes default data** via `setup_tenant_defaults()` utility

The default data initialization includes:
- Current academic year with start/end dates
- Semesters (2) with appropriate date ranges
- Marking periods (grading periods) within semesters
- Divisions (Preschool, Elementary, Middle, High School)
- Grade levels (Nursery 1 through Grade 12)
- Sections (class sections for each grade level)
- Subjects (academic subjects for different grade levels)
- Section-subject assignments
- Periods (daily school periods)
- Period times (time slots for each period)

**Implementation Details:**

```python
# In CreateTenantSerializer.create()
try:
    from defaults.utils import setup_tenant_defaults
    setup_tenant_defaults(tenant, owner)
except Exception as e:
    logger.error(f"Failed to initialize default data for tenant {tenant.name}: {e}")
    # Tenant is created but default data initialization failed
    # This allows manual retry or fixing the issue
```

The default data setup is resilient - if it fails, the tenant is still created but logged for manual intervention.

**Reference:**
- `defaults/utils.py` - setup_tenant_defaults() wrapper function
- `defaults/run.py` - run_data_creation() actual implementation

## 2. Tenant Users Endpoint

### Endpoint
```
GET /api/v1/tenants/{schema_name}/users/
```

**Location:** `core/views.py` - TenantViewSet.users()

### Features
- Lists all users who have access to a specific tenant
- Queries UserTenantPermissions in the tenant schema
- Returns User objects from public schema (global users)
- Supports filtering and search
- Paginated results (20 per page, configurable up to 100)

### Query Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| search | string | Search across name, email, username, id_number | `?search=john` |
| role | string | Filter by role (comma-separated for multiple) | `?role=TEACHER,ADMIN` |
| is_active | boolean | Filter by active status | `?is_active=true` |
| ordering | string | Sort results | `?ordering=-date_joined` |
| page | integer | Page number | `?page=2` |
| page_size | integer | Results per page (max 100) | `?page_size=50` |

### Valid Ordering Options
- `first_name`, `-first_name`
- `last_name`, `-last_name`
- `username`, `-username`
- `email`, `-email`
- `role`, `-role`
- `date_joined`, `-date_joined` (default)
- `last_login`, `-last_login`
- `id_number`, `-id_number`

### Example Requests

```bash
# Get all users for a tenant
GET /api/v1/tenants/myschool/users/

# Search for users named "john" who are teachers
GET /api/v1/tenants/myschool/users/?search=john&role=TEACHER

# Get active admins, sorted by name
GET /api/v1/tenants/myschool/users/?role=ADMIN&is_active=true&ordering=last_name

# Paginated results with custom page size
GET /api/v1/tenants/myschool/users/?page=1&page_size=50
```

### Response Format

```json
{
    "count": 45,
    "next": "http://api.example.com/api/v1/tenants/myschool/users/?page=2",
    "previous": null,
    "results": [
        {
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "username": "jdoe",
            "email": "jdoe@example.com",
            "id_number": "STF001",
            "first_name": "John",
            "last_name": "Doe",
            "account_type": "TENANT",
            "photo": "http://api.example.com/media/users/jdoe.jpg",
            "is_active": true,
            "last_login": "2024-01-15T10:30:00Z",
            "role": "TEACHER",
            "gender": "male",
            "tenants": [
                {
                    "id": "456e7890-e89b-12d3-a456-426614174001",
                    "schema_name": "myschool",
                    "workspace": "myschool",
                    "name": "My School",
                    "logo": "http://api.example.com/media/logo/myschool.png"
                }
            ]
        }
    ]
}
```

## 3. String-Based User Account References

### Problem
Cross-schema foreign keys don't work properly in django-tenants multi-tenant architecture. Previously, Student and Staff models had OneToOneField to User model, creating problematic FK constraints across schemas (tenant schema → public schema).

### Solution
Changed from FK relationships to string-based references using `user_account_id_number` CharField.

### Changes Made

#### Student Model
**Location:** `students/models/student.py`

**Before:**
```python
user_account = models.OneToOneField(
    "users.user",
    on_delete=models.CASCADE,
    related_name="student_account",
    null=True,
    blank=True,
)
```

**After:**
```python
user_account_id_number = models.CharField(
    max_length=50,
    null=True,
    blank=True,
    default=None,
    help_text="User ID number (string reference to User.id_number in public schema). Loose coupling instead of cross-schema FK."
)
```

#### Staff Model
**Location:** `staff/models.py`

**Before:**
```python
user_account = models.OneToOneField(
    "users.user",
    on_delete=models.CASCADE,
    related_name="staff_account",
    null=True,
    blank=True,
)
```

**After:**
```python
user_account_id_number = models.CharField(
    max_length=50,
    null=True,
    blank=True,
    default=None,
    help_text="User ID number (string reference to User.id_number in public schema). Loose coupling instead of cross-schema FK."
)
```

### Benefits
1. **Schema Isolation:** No cross-schema FK constraints
2. **Flexibility:** Users can be deleted/modified without cascade issues
3. **Performance:** Simpler queries without complex joins across schemas
4. **Portability:** Easier to migrate tenants to separate databases in the future

### Usage Pattern

**Creating User Accounts:**
```python
# In common/utils.py - StudentBulkProcessor.create_user_accounts()

# Create User in public schema
user = User.objects.create(
    email=student.email,
    id_number=student.id_number,
    # ... other fields
)

# Store string reference in tenant schema
student.user_account_id_number = student.id_number
student.save(update_fields=['user_account_id_number'])
```

**Looking Up User:**
```python
# Get student's user account
if student.user_account_id_number:
    try:
        user = User.objects.get(id_number=student.user_account_id_number)
    except User.DoesNotExist:
        user = None
```

## 4. Model Reference Fixes

### CustomUser → User
Fixed incorrect model references throughout the codebase.

**Models Fixed:**
- `students/models/student.py` - All FK references
- `staff/models.py` - All FK references (Department, Position, PositionCategory, etc.)
- `common/utils.py` - StudentBulkProcessor user creation logic

The correct model name is `users.User` (which extends UserProfile from django-tenant-users), not `users.user`.

### School → Tenant
Fixed legacy references from old single-tenant architecture.

**Files Fixed:**
- `academics/signals.py` - Signal receivers for logo upload/replacement

**Changes:**
- `from core.models import School` → `from core.models import Tenant`
- `@receiver(post_save, sender=School)` → `@receiver(post_save, sender=Tenant)`
- `@receiver(pre_save, sender=School)` → `@receiver(pre_save, sender=Tenant)`
- `school_logo_upload` → `tenant_logo_upload`

## 5. Migration Requirements

### Database Migration Needed
After deploying these changes, run migrations to:

1. **Add new CharField fields:**
   - `Student.user_account_id_number`
   - `Staff.user_account_id_number`

2. **Remove old FK fields:**
   - `Student.user_account` (OneToOneField)
   - `Staff.user_account` (OneToOneField)

### Data Migration Script

You'll need to create a data migration to:

1. Copy existing FK values to string references
2. Drop old FK fields
3. Add new CharField fields

**Example Migration:**
```python
# students/migrations/0XXX_convert_user_account_to_string.py

from django.db import migrations

def forward_func(apps, schema_editor):
    Student = apps.get_model('students', 'Student')
    User = apps.get_model('users', 'User')
    
    for student in Student.objects.filter(user_account__isnull=False):
        try:
            user = User.objects.get(id=student.user_account_id)
            student.user_account_id_number = user.id_number
            student.save(update_fields=['user_account_id_number'])
        except User.DoesNotExist:
            pass

def reverse_func(apps, schema_editor):
    # Reverse migration would require FK field to exist
    pass

class Migration(migrations.Migration):
    dependencies = [
        ('students', '0XXX_previous_migration'),
    ]
    
    operations = [
        # Add new field
        migrations.AddField(
            model_name='student',
            name='user_account_id_number',
            field=models.CharField(max_length=50, null=True, blank=True),
        ),
        # Run data migration
        migrations.RunPython(forward_func, reverse_func),
        # Remove old field
        migrations.RemoveField(
            model_name='student',
            name='user_account',
        ),
    ]
```

**Note:** Similar migration needed for Staff model.

## 6. API Endpoints Summary

### Tenant Management
- `GET /api/v1/tenants/` - List all tenants
- `POST /api/v1/tenants/` - Create new tenant (with auto schema + defaults)
- `GET /api/v1/tenants/{schema_name}/` - Get tenant details
- `PATCH /api/v1/tenants/{schema_name}/` - Update tenant
- `DELETE /api/v1/tenants/{schema_name}/` - Soft delete tenant
- `GET /api/v1/tenants/{schema_name}/users/` - **NEW:** List tenant users

### Permissions
- List/Retrieve: AllowAny (public endpoints for routing/branding)
- Create/Update/Delete: IsAuthenticated + IsAdminUser
- Users endpoint: IsAuthenticated + IsAdminUser

### Public Schema Requirement
All tenant management operations must be performed in the public schema. The API validates this and returns an error if called from a tenant schema.

## 7. Testing Recommendations

### Test Tenant Creation
```bash
POST /api/v1/tenants/
{
    "name": "Test School",
    "short_name": "Test",
    "domain": "test.localhost",
    "owner_email": "admin@test.com"
}
```

**Verify:**
- Schema created in database
- Default academic years, grades, subjects created
- Owner has superuser access in tenant schema

### Test User Listing
```bash
GET /api/v1/tenants/test/users/
```

**Verify:**
- Owner user appears in results
- All superadmin users appear
- Pagination works
- Filtering/search works

### Test String References
```python
# After migration, verify:
from students.models import Student
from users.models import User

student = Student.objects.first()
print(student.user_account_id_number)  # Should print user's id_number

# Lookup should work
user = User.objects.get(id_number=student.user_account_id_number)
print(user.email)
```

## 8. Configuration Checklist

- [x] Tenant model has `auto_create_schema = True`
- [x] CreateTenantSerializer calls `setup_tenant_defaults()`
- [x] TenantViewSet has users() action endpoint
- [x] Student model uses `user_account_id_number` CharField
- [x] Staff model uses `user_account_id_number` CharField
- [x] All CustomUser references changed to User
- [x] All School signal references changed to Tenant
- [x] TenantUserPagination configured (20/page, max 100)
- [ ] Database migrations created and run
- [ ] Data migration to populate id_number fields
- [ ] Tests updated for new string reference pattern

## 9. Future Improvements

1. **Tenant User Roles:**
   - Add endpoint to view/manage per-tenant user roles
   - Currently roles are in User model (global), should be in UserTenantPermissions (per-tenant)

2. **Tenant Deletion:**
   - Current implementation is soft delete (status='deleted')
   - Consider adding hard delete endpoint for permanent removal (with safeguards)

3. **Default Data Customization:**
   - Allow customizing default data during tenant creation
   - Add endpoint to re-run default data setup for existing tenants

4. **Performance:**
   - Consider caching tenant users list
   - Add database indexes on user_account_id_number fields

5. **Validation:**
   - Add validation to ensure user_account_id_number references exist in User table
   - Add cleanup task to find orphaned references

## References

- django-tenants: https://django-tenants.readthedocs.io/
- django-tenant-users: https://django-tenant-users.readthedocs.io/
- Multi-tenant best practices: Avoid cross-schema FKs, use string references

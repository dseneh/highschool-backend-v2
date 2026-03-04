# Authentication & Authorization Implementation Plan

## Overview
Complete auth system for multi-tenant school management with role-based access control (RBAC) and fine-grained privilege management.

## Current Architecture

### User Model
- Extends `UserProfile` from django-tenant-users
- Fields: email, username, first_name, last_name, id_number, gender, account_type, role, photo, is_default_password
- Rules: Global user (public schema), can belong to multiple tenants via TenantUser model

### Account Types
```python
UserAccountType:
  - GLOBAL: System admin
  - STAFF: School staff member
  - STUDENT: Student with enrollment
  - PARENT: Parent/guardian
  - OTHER: Default/generic
```

### Roles (8 levels)
```python
SUPERADMIN     → System-level administrator (all permissions)
ADMIN          → School administrator (all school permissions)
REGISTRAR      → Enrollment & records management
ACCOUNTANT     → Finance/billing management
TEACHER        → Subject instruction & grading (restricted)
STUDENT        → Student account (view own data)
PARENT         → Parent account (view child data)
VIEWER         → Read-only access
DATA_ENTRY     → Data input only (no deletion)
```

### Existing Privileges (40+ defined)
- CORE_VIEW, CORE_MANAGE
- FINANCE_VIEW, FINANCE_MANAGE
- GRADING_VIEW, GRADING_MANAGE, GRADING_ENTER, GRADING_REVIEW, GRADING_APPROVE, GRADING_REJECT
- STUDENTS_VIEW, STUDENTS_MANAGE, STUDENT_ENROLL, STUDENT_EDIT, STUDENT_DELETE
- SETTINGS_GRADING_MANAGE
- TRANSACTION_CREATE, TRANSACTION_UPDATE, TRANSACTION_DELETE, TRANSACTION_APPROVE, TRANSACTION_CANCEL

## Implementation Strategy

### Phase 1: Core Models (NEW)
Create missing models in `/users/models.py`:

#### 1. SpecialPrivilege Model
```python
class SpecialPrivilege(models.Model):
    """User-specific privilege assignment (override role defaults)"""
    - id: UUID
    - user: FK(User)
    - code: CharField (from permissions.PRIVILEGES)
    - granted_by: FK(User)
    - granted_at: DateTime
    - expires_at: DateTime (optional - for temporary grants)
    - notes: TextField
    
    Unique constraint: (user, code) per tenant
    Indexes: user, code, granted_at
```

#### 2. RoleDefaultPrivilege Model
```python
class RoleDefaultPrivilege(models.Model):
    """Default privilege set for each role"""
    - id: UUID
    - role: CharField (choices=Roles.choices())
    - privilege_code: CharField
    - applies_to_account_types: JSONField (list of UserAccountType values)
    - notes: TextField
    
    Unique constraint: (role, privilege_code) per tenant
    Data: Populated via migration/fixture
```

#### 3. StudentAccount Model
```python
class StudentAccount(models.Model):
    """Links a Student record to a User account"""
    - id: UUID
    - student: FK(Student, unique=True)
    - user: FK(User, unique=True) OR id_number CharField
    - created_at: DateTime
    - created_by: FK(User)
    
    Purpose: Enable user lookup by student, vice versa
    Index: student, user
```

#### 4. StaffAccount Model
```python
class StaffAccount(models.Model):
    """Links a Staff record to a User account"""
    - id: UUID
    - staff: FK(Staff, unique=True)
    - user: FK(User, unique=True) OR id_number CharField
    - created_at: DateTime
    - created_by: FK(User)
    
    Purpose: Enable user lookup by staff, vice versa
    Index: staff, user
```

#### 5. ParentAccount Model
```python
class ParentAccount(models.Model):
    """Links StudentGuardian records to a User account (parent can have multiple guardians)"""
    - id: UUID
    - guardian: FK(StudentGuardian, many=True via related_name)
    - user: FK(User, unique=True) OR id_number CharField
    - created_at: DateTime
    - created_by: FK(User)
    
    Purpose: One parent user can manage multiple guardians
    Index: user, guardian
```

### Phase 2: Access Control Logic

#### Update User Model With Privilege Helpers
```python
# In users/models.py User class:
def has_privilege(self, privilege_code: str) -> bool:
    """Check if user has specific privilege (via role or explicit grant)"""
    if self.role == Roles.SUPERADMIN or self.is_superuser:
        return True
    
    # Check special privileges
    return self.special_privileges.filter(code=privilege_code).exists()

def get_privileges(self) -> List[str]:
    """Get all privileges (role defaults + special)"""
    # Get role defaults from RoleDefaultPrivilege
    # Add special privileges
    # Return unique list
    
def can_manage_user(self, target_user: User) -> bool:
    """Check if current user can manage target user"""
    if self.role == Roles.SUPERADMIN or self.is_superuser:
        return True
    if self.role == Roles.ADMIN:
        return target_user.role != Roles.SUPERADMIN
    return False

def can_impersonate_as_role(self, target_role: str) -> bool:
    """Check if user can impersonate as target role"""
    # Only ADMIN+ can impersonate other roles
    # SUPERADMIN can impersonate anyone
```

#### Update AccessPolicy (BaseSchoolAccessPolicy)
Add condition methods:
```python
def has_any_privilege_in_role(self, request, view, action, 
                              privilege_codes: str) -> bool:
    """Check any privilege, considering role defaults"""
    
def is_tenant_admin(self, request, view, action) -> bool:
    """Check if ADMIN or SUPERADMIN for this tenant"""
    
def owns_resource(self, request, view, action) -> bool:
    """Check if user owns the resource (student viewing own, etc)"""
    
def is_account_type(self, request, view, action, 
                   account_types: str) -> bool:
    """Check user's account type (e.g., is_account_type:STUDENT,STAFF)"""
```

### Phase 3: Role-Based Default Privileges

#### SUPERADMIN
- All 40+ privileges
- Can grant/revoke privileges
- Can impersonate any user

#### ADMIN (School Admin)
- CORE_MANAGE, FINANCE_MANAGE, GRADING_MANAGE, STUDENTS_MANAGE
- SETTINGS_GRADING_MANAGE
- All transactional actions (TRANSACTION_*)
- Can grant privileges to tenant users only
- Cannot manage other ADMIN accounts

#### REGISTRAR
- CORE_VIEW, STUDENTS_MANAGE, STUDENT_ENROLL, STUDENT_EDIT
- STUDENT_DELETE (with restrictions)
- Cannot modify finance or grading

#### ACCOUNTANT
- FINANCE_MANAGE, TRANSACTION_*
- STUDENTS_VIEW (read bills only)
- Cannot modify grading or core

#### TEACHER
- GRADING_ENTER, GRADING_MANAGE (view only)
- STUDENTS_VIEW
- Can only grade own classes
- Can view own student roster

#### STUDENT
- STUDENTS_VIEW (own record only)
- GRADING_VIEW (own grades only)
- FINANCE_VIEW (own billing only)

#### PARENT
- STUDENTS_VIEW (own children)
- GRADING_VIEW (own children only)
- FINANCE_VIEW (own children only)

#### VIEWER
- All *_VIEW privileges (read-only)
- No write access

#### DATA_ENTRY
- STUDENTS_MANAGE (view/edit only, no delete)
- CORE_VIEW, FINANCE_VIEW
- Can input data but not delete

### Phase 4: Enforcement Points

#### Serializers
Add `SerializerMethodField` validators that check:
- User has required privilege
- User can access tenant
- User can access specific resource (own record)

#### Views/Viewsets
Add permission classes:
```python
class SchoolAccessPermission(BasePermission):
    """Check tenant + role + privilege"""
    def has_permission(self, request, view):
        # Check tenant membership
        # Check required privilege
        return True/False
    
    def has_object_permission(self, request, view, obj):
        # Check specific object access (own record, etc)
        return True/False
```

#### Queryset Filtering
Auto-filter querysets by tenant and user access:
```python
# In viewsets:
def get_queryset(self):
    qs = super().get_queryset()
    user = self.request.user
    
    # Students see only own enrollments
    if user.role == Roles.STUDENT:
        qs = qs.filter(student__user_account_id_number=user.id_number)
    
    # Parents see children's data
    if user.role == Roles.PARENT:
        student_ids = StudentGuardian.objects.filter(
            user=user
        ).values_list('student_id', flat=True)
        qs = qs.filter(student_id__in=student_ids)
    
    return qs
```

## Migration Plan

### Step 1: Create Models
- Add 5 new models to users/models.py
- Create migration: `python manage.py makemigrations users`

### Step 2: Populate Default Privileges
- Create data migration: `python manage.py makemigrations users --empty --name populate_role_privileges`
- Add RoleDefaultPrivilege entries for all roles

### Step 3: Link Existing Accounts
- Create management command to auto-link Student/Staff models to Users
- Update User.user_account_id_number → StudentAccount/StaffAccount if both exist

### Step 4: Update Views & Serializers
- Add permission classes to all viewsets
- Add privilege checks to serializers where needed
- Add queryset filtering

### Step 5: Test & Document
- Create test cases for privilege checks
- Document API permission requirements
- Update OpenAPI/Swagger docs

## Security Considerations

### Multi-Tenant Isolation
- All queries must include tenant context (via django-tenants)
- Cross-tenant access should be explicitly denied
- SpecialPrivilege/RoleDefaultPrivilege are tenant-specific

### Privilege Expiration
- SpecialPrivilege.expires_at: temporary privilege grants
- Cron job to auto-revoke expired privileges

### Audit Trail
- Track who granted/revoked privileges
- Log user account creation/linking
- Log privilege-based access denials (DEBUG level)

### Default Password Policy
- User.is_default_password: Force change on first login
- Implement in frontend + backend login endpoint
- Generate secure random passwords for new accounts

### Rate Limiting
- Implement for login endpoint (slow brute force)
- Implement for privilege-sensitive endpoints (TRANSACTION_APPROVE, etc)

## API Endpoints to Update

### Students App
- `PATCH /students/{id}/` → Requires STUDENT_EDIT
- `DELETE /students/{id}/` → Requires STUDENT_DELETE
- `POST /enrollments/` → Requires STUDENT_ENROLL
- `GET /students/{id}/billing/` → Requires STUDENTS_VIEW, ownership check

### Grading App
- `POST /grades/` → Requires GRADING_ENTER
- `PATCH /grades/{id}/` → Requires GRADING_ENTER or GRADING_REVIEW
- `POST /gradebooks/{id}/approve/` → Requires GRADING_APPROVE
- `POST /gradebooks/{id}/reject/` → Requires GRADING_REJECT

### Finance App
- `POST /transactions/` → Requires TRANSACTION_CREATE
- `DELETE /transactions/{id}/` → Requires TRANSACTION_DELETE
- `PATCH /transactions/{id}/approve/` → Requires TRANSACTION_APPROVE
- `PATCH /transactions/{id}/cancel/` → Requires TRANSACTION_CANCEL

## Frontend Integration Points

### Auth Store
- On login, fetch user's full privilege list
- Cache locally (1-hour TTL)
- Use for UI element visibility

### Route Guards
- Check role + privilege before rendering routes
- Show "Access Denied" for insufficient privileges

### Serialization
- Filter form fields based on privileges
- Show/hide action buttons (delete, approve, etc)
- Disable inputs for read-only access

---

## Implementation Order
1. ✅ Create models (users/models.py)
2. ✅ Create migration with defaults
3. → Add permission classes + filters to views
4. → Update frontend with permission checks
5. → Add audit logging
6. → Add rate limiting

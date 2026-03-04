# Backend Authentication & Authorization Implementation

## What Was Added

### 1. New Models (users/models.py)

#### SpecialPrivilege
- **Purpose**: Grant user-specific privileges that override role defaults
- **Use Cases**:
  - Temporary elevated access (e.g., teacher can approve grades for one marking period)
  - Fine-grained permission control independent of role
- **Key Fields**:
  - `user`: FK to User
  - `code`: Privilege code (e.g., "GRADING_APPROVE")
  - `expires_at`: Auto-revoke privilege after date (optional)
  - `granted_by`: Audit trail
  - `notes`: Reason for grant
- **Unique Constraint**: (user, code) per tenant
- **Auto-Expires**: Background job should clean up expired privileges

#### RoleDefaultPrivilege
- **Purpose**: Define what privileges each role has by default
- **Population**: Via migration (0003_populate_role_privileges.py)
- **Key Fields**:
  - `role`: Role code (ADMIN, TEACHER, STUDENT, etc.)
  - `privilege_code`: Single privilege to grant
  - `applies_to_account_types`: Which account types get this privilege
  - `notes`: Why this privilege is granted
- **Unique Constraint**: (role, privilege_code) globally

#### StudentAccount
- **Purpose**: Link Student (tenant schema) to User (public schema)
- **Why Needed**: Avoid cross-schema foreign keys; enable user ↔ student lookup
- **Key Fields**:
  - `student_id`: Reference to Student.id_number (loose coupling)
  - `user`: OneToOne to User (in public schema)
  - `user_id_number`: Alternative loose coupling via id_number string

#### StaffAccount
- **Purpose**: Link Staff (tenant schema) to User (public schema)
- **Why Needed**: Same as StudentAccount - bi-directional lookup
- **Key Fields**:
  - `staff_id`: Reference to Staff.id_number
  - `user`: OneToOne to User
  - `user_id_number`: Alternative loose coupling

#### ParentAccount
- **Purpose**: Link parent/guardian (from StudentGuardian) to User account
- **Why Needed**: One parent user might manage multiple children/guardians
- **Key Fields**:
  - `user`: OneToOne to User
  - `parent_email`: From StudentGuardian email field
  - `parent_phone`: From StudentGuardian phone field
  - `user_id_number`: Alternative loose coupling

### 2. User Model Enhancements

Added privilege helper methods to User:

```python
# Check specific privilege
user.has_privilege("GRADING_APPROVE")  # → True/False

# Get all privileges
user.get_privileges()  # → ["GRADING_ENTER", "STUDENTS_VIEW", ...]

# Manage other users
user.can_manage_user(target_user)  # → True/False (ADMIN only)

# Grant privileges
user.can_grant_privilege("GRADING_APPROVE")  # → True/False

# Shortcuts
user.is_admin  # SUPERADMIN or ADMIN
user.is_staff_user  # account_type == STAFF
user.is_student_user  # account_type == STUDENT
user.is_parent_user  # account_type == PARENT
```

### 3. Admin Interface

Registered all models in Django admin:
- **UserAdmin**: Updated to show role + account_type, role default privileges view
- **SpecialPrivilegeAdmin**: Grant/revoke special privileges with expiration dates
- **RoleDefaultPrivilegeAdmin**: View/edit role privilege mappings (read-mostly)
- **Student/Staff/ParentAccountAdmin**: Manage account links with audit trails

### 4. Default Privilege Mappings (Migration)

Populated via `0003_populate_role_privileges.py`:

**SUPERADMIN**: All 20+ privileges (system audit)
**ADMIN**: All school-level privileges except core system
**REGISTRAR**: CORE_VIEW, STUDENTS_*, STUDENT_ENROLL/EDIT
**ACCOUNTANT**: FINANCE_*, TRANSACTION_*, STUDENTS_VIEW
**TEACHER**: GRADING_ENTER, GRADING_VIEW, STUDENTS_VIEW
**STUDENT**: STUDENTS_VIEW (self), GRADING_VIEW (self), FINANCE_VIEW (self)
**PARENT**: STUDENTS_VIEW (children), GRADING_VIEW (children), FINANCE_VIEW (children)
**VIEWER**: All *_VIEW privileges (read-only)
**DATA_ENTRY**: CORE_VIEW, STUDENTS_*, FINANCE_VIEW, TRANSACTION_CREATE (no delete)

## How to Use

### 1. Check Permissions in Views

```python
from rest_framework import permissions

class HasStudentManagePrivilege(permissions.BasePermission):
    """Check for STUDENTS_MANAGE privilege"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.has_privilege("STUDENTS_MANAGE")

# In ViewSet
class StudentViewSet(viewsets.ModelViewSet):
    permission_classes = [HasStudentManagePrivilege]
```

### 2. Filter Querysets by User Permissions

```python
class StudentViewSet(viewsets.ModelViewSet):
    
    def get_queryset(self):
        qs = Student.objects.all()
        user = self.request.user
        
        # Students see only own record
        if user.role == Roles.STUDENT:
            try:
                account = StudentAccount.objects.get(user=user)
                qs = qs.filter(id_number=account.student_id)
            except StudentAccount.DoesNotExist:
                qs = qs.none()
        
        # Parents see only children
        elif user.role == Roles.PARENT:
            try:
                account = ParentAccount.objects.get(user=user)
                student_ids = StudentGuardian.objects.filter(
                    # Match guardian to student
                    # Then get those student IDs
                ).values_list('student_id', flat=True)
                qs = qs.filter(id__in=student_ids)
            except ParentAccount.DoesNotExist:
                qs = qs.none()
        
        return qs
```

### 3. Enforce Privileges in Serializers

```python
from rest_framework import serializers

class StudentSerializer(serializers.ModelSerializer):
    
    def validate(self, attrs):
        # Check if user can edit sensitive fields
        user = self.context['request'].user
        
        if 'grade_level' in attrs and not user.has_privilege("STUDENT_EDIT"):
            raise serializers.ValidationError(
                {"grade_level": "You don't have permission to change grade level"}
            )
        
        return attrs
    
    class Meta:
        model = Student
        fields = ['id_number', 'first_name', 'last_name', 'grade_level']
```

### 4. Using AccessPolicy (Existing System)

Update access policies in views with new conditions:

```python
class StudentAccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["list", "retrieve"],
            "principal": ["authenticated"],
            "effect": "allow",
            "condition": "has_privilege:STUDENTS_VIEW"
        },
        {
            "action": ["create", "update"],
            "principal": ["authenticated"],
            "effect": "allow",
            "condition": "has_privilege:STUDENT_EDIT"
        },
        {
            "action": ["destroy"],
            "principal": ["authenticated"],
            "effect": "allow",
            "condition": "has_privilege:STUDENT_DELETE"
        },
    ]
```

## Account Linking Workflow

### For Students:

1. **User creates a student account** → `User.account_type = STUDENT`, `User.role = STUDENT`
2. **Student record created** → `Student.user_account_id_number` set to User.id_number
3. **StudentAccount link created** → Links Student & User bidirectionally
4. **On Login**: Fetch student via `StudentAccount.objects.select_related('user')`

### For Staff:

1. **User created** → `User.account_type = STAFF`, `User.role = TEACHER/ADMIN/etc`
2. **Staff record created** → `Staff.user_account_id_number` set to User.id_number
3. **StaffAccount link created** → Links Staff & User
4. **On Login**: Fetch staff via `StaffAccount.objects.select_related('staff')`

### For Parents:

1. **StudentGuardian records exist** → Contain parent email/phone
2. **User created** → `User.account_type = PARENT`, `User.role = PARENT`
3. **ParentAccount link created** → Links user to parent email/phone
4. **Match guardians** → Query StudentGuardians by email/phone, fetch students
5. **On Login**: Fetch children via `StudentGuardian.objects.filter(email=user.email)`

## Migration Steps

```bash
# 1. Create initial models
python manage.py makemigrations users

# 2. Apply migrations (creates tables)
python manage.py migrate

# 3. Data migration runs (populates role privileges)
# Already included in migration 0003

# 4. Create account links for existing users
python manage.py create_account_links  # Create this management command

# 5. Verify in Django admin
# - Check RoleDefaultPrivilege populated
# - Check no SpecialPrivilege entries (normal)
# - Check no Account links yet (unless you ran step 4)
```

## Testing

### Unit Tests for Privileges

```python
from django.test import TestCase
from users.models import User, SpecialPrivilege, RoleDefaultPrivilege

class PrivilegeTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create(
            email='teacher@school.com',
            role='teacher',
            account_type='staff'
        )
    
    def test_role_has_default_privileges(self):
        """Teacher should have GRADING_ENTER by default"""
        self.assertTrue(self.teacher.has_privilege("GRADING_ENTER"))
        self.assertFalse(self.teacher.has_privilege("GRADING_APPROVE"))
    
    def test_special_privilege_grant(self):
        """Can grant special privilege independent of role"""
        SpecialPrivilege.objects.create(
            user=self.teacher,
            code="GRADING_APPROVE",
            notes="Temporary approval for Q3"
        )
        self.assertTrue(self.teacher.has_privilege("GRADING_APPROVE"))
    
    def test_privilege_expiration(self):
        """Expired privilege should not count"""
        from django.utils import timezone
        past = timezone.now() - timezone.timedelta(days=1)
        
        SpecialPrivilege.objects.create(
            user=self.teacher,
            code="GRADING_APPROVE",
            expires_at=past
        )
        self.assertFalse(self.teacher.has_privilege("GRADING_APPROVE"))
```

## Next Steps (Frontend)

The frontend will need to:

1. **Fetch user privileges** on login:
   ```typescript
   const user = await fetchUser();  // Includes user.get_privileges()
   store.setUserPrivileges(user.privileges);
   ```

2. **Use privileges for UI visibility**:
   ```typescript
   if (user.hasPrivilege("STUDENT_DELETE")) {
     showDeleteButton = true;
   }
   ```

3. **Route guards**:
   ```typescript
   CanActivate: checkUserPrivilege("STUDENTS_MANAGE")
   ```

4. **Form field visibility**:
   ```typescript
   if (!user.hasPrivilege("STUDENT_EDIT")) {
     disableField("grade_level");
   }
   ```

## Security Notes

### Multi-Tenant Isolation
- All queries automatically scoped to current tenant (via django-tenants)
- SpecialPrivilege queries respect tenant schema boundaries

### Privilege Inheritance
- SUPERADMIN always passes all checks (short-circuit)
- Child privileges inherit parent scope if needed

### Audit Trail
- All grants tracked with granted_by + granted_at
- All account links track created_by + created_at
- Consider adding audit logging to privilege changes

### Rate Limiting
Consider rate-limiting:
- Login attempts (5 per minute per IP)
- Privilege-sensitive endpoints (TRANSACTION_APPROVE, etc)
- Account link creation

## Files Changed

- `users/models.py`: +400 lines (5 new models + User helpers)
- `users/admin.py`: +150 lines (5 new admin classes)
- `users/migrations/0003_*.py`: Migration for role privileges
- `AUTH_IMPLEMENTATION_PLAN.md`: This document

---

**Ready for**: View/Serializer updates, API endpoint enforcement, Frontend integration

# Auth System Quick Reference

## Privilege Hierarchy

```
SUPERADMIN (🔑 All privileges)
    ↓↓↓
ADMIN (School-wide management)
    ├─ REGISTRAR (Enrollment only)
    ├─ ACCOUNTANT (Finance only)
    └─ TEACHER (Grading only)
         ├─ STUDENT (Self + READ access)
         └─ PARENT (Children + READ access)

VIEWER (Read-only all)
DATA_ENTRY (Input only, no delete)
```

## Core Privilege Codes

### Configuration Management
- `CORE_VIEW`: View academic setup (grades, periods, sections)
- `CORE_MANAGE`: Create/edit/delete academic setup

### Student Management
- `STUDENTS_VIEW`: View student records
- `STUDENTS_MANAGE`: Generic student management
- `STUDENT_ENROLL`: Create enrollments
- `STUDENT_EDIT`: Modify student/enrollment records
- `STUDENT_DELETE`: Remove students (ADMIN only)

### Grading
- `GRADING_VIEW`: View grades/gradebooks
- `GRADING_MANAGE`: Configure grading (templates, scales)
- `GRADING_ENTER`: Input grades
- `GRADING_REVIEW`: Mark grades as reviewed
- `GRADING_APPROVE`: Approve grade submissions
- `GRADING_REJECT`: Reject and return to teacher
- `SETTINGS_GRADING_MANAGE`: Configure grading policies

### Finance
- `FINANCE_VIEW`: View all financial data
- `FINANCE_MANAGE`: Configure finance (fees, methods)
- `TRANSACTION_CREATE`: Record transactions
- `TRANSACTION_UPDATE`: Modify transactions
- `TRANSACTION_DELETE`: Remove transactions
- `TRANSACTION_APPROVE`: Approve pending payments
- `TRANSACTION_CANCEL`: Cancel transactions

## Decision Trees for Permission Checks

### Can user edit student?
```
if user.role == SUPERADMIN → YES
if user.role == ADMIN → YES
if user.has_privilege(STUDENT_EDIT) → YES
if owns student (account_type STUDENT, self) → YES (limited fields)
if is parent of student → YES (limited fields)
else → NO
```

### Can user view student?
```
if user.has_privilege(STUDENTS_VIEW) → YES
if owns student (account_type STUDENT, self) → YES
if is parent of student → YES
else → NO
```

### Can user create grades?
```
if user.has_privilege(GRADING_ENTER) → YES
else → NO
```

### Can user approve grades?
```
if user.role == SUPERADMIN → YES
if user.role == ADMIN → YES
if user.has_privilege(GRADING_APPROVE) → YES
else → NO
```

### Can user access financial data?
```
if user.has_privilege(FINANCE_VIEW) → YES
if user.has_privilege(FINANCE_MANAGE) → YES
if student accessing own billing → YES
if parent accessing children's billing → YES
else → NO
```

## Common View Patterns

### Admin/Read-only Endpoint
```python
permission_classes = [
    IsAuthenticated,
    BaseSchoolAccessPolicy
]

statements = [{
    "action": ["list", "retrieve"],
    "principal": ["authenticated"],
    "effect": "allow",
    "condition": "has_privilege:CORE_VIEW"
}]
```

### Writer Endpoint (Create/Update)
```python
statements = [
    {
        "action": ["create", "update", "partial_update"],
        "principal": ["authenticated"],
        "effect": "allow",
        "condition": "has_privilege:STUDENTS_MANAGE"
    }
]
```

### Admin-Only Endpoint
```python
statements = [{
    "action": ["destroy"],
    "principal": ["authenticated"],
    "effect": "allow",
    "condition": "is_role_in:SUPERADMIN,ADMIN"
}]
```

### Ownership-Based Access
```python
def has_object_permission(self, request, view, obj):
    # Student viewing self
    if request.user.role == Roles.STUDENT:
        return StudentAccount.objects.filter(
            user=request.user,
            student_id=obj.id_number
        ).exists()
    
    # Parent viewing child
    if request.user.role == Roles.PARENT:
        return StudentGuardian.objects.filter(
            email=request.user.email,
            student__id_number=obj.id_number
        ).exists()
    
    # Staff/Admin viewing any
    return request.user.has_privilege("STUDENTS_VIEW")
```

## Quick Test Cases

Verify these work in your tests:

### User Creation
```python
# ✅ Create admin user
admin = User.objects.create(
    email='admin@school.com',
    role='admin',
    account_type='staff'
)

# ✅ Verify role privileges auto-apply
assert admin.has_privilege("STUDENTS_MANAGE")
assert admin.has_privilege("GRADING_MANAGE")

# ❌ But not those exceeding admin level
assert not admin.has_privilege("TRANSACTION_DELETE")
```

### Special Privilege Granting
```python
# ✅ Grant teacher temporary approval power
teacher = User.objects.get(email='teacher@school.com')
grant = SpecialPrivilege.objects.create(
    user=teacher,
    code="GRADING_APPROVE",
    notes="Q3 only"
)

# ✅ Verify privilege now works
assert teacher.has_privilege("GRADING_APPROVE")

# ✅ Verify it's in get_privileges()
assert "GRADING_APPROVE" in teacher.get_privileges()

# ❌ Delete grant
grant.delete()
assert not teacher.has_privilege("GRADING_APPROVE")
```

### Account Linking
```python
# ✅ Student with user account
student = Student.objects.create(id_number='001234')
user = User.objects.create(id_number='S001234')
account = StudentAccount.objects.create(
    student_id='001234',
    user=user
)

# ✅ User can access own billing
assert account.user == user
assert StudentAccount.objects.filter(user=user).exists()

# ✅ Student can see own enrollment
assert user.has_privilege("STUDENTS_VIEW")
assert user.student_account.student_id == '001234'
```

## API Endpoint Examples

### List Students (with privilege check)
```
GET /api/v2/students/
Headers: Authorization: Bearer {token}

✅ Returns all if user.has_privilege(STUDENTS_VIEW)
✅ Returns own if user.role == STUDENT
✅ Returns children if user.role == PARENT
❌ 403 Forbidden if no privilege
```

### Update Student (with privilege check)
```
PATCH /api/v2/students/001234/
Headers: Authorization: Bearer {token}
Body: { "first_name": "John" }

✅ Success if user.has_privilege(STUDENT_EDIT)
✅ Success if owns student + limited fields
❌ 403 Forbidden if no privilege
❌ 400 Bad Request if trying to modify restricted field
```

### Create Grade (with privilege check)
```
POST /api/v2/grades/
Headers: Authorization: Bearer {token}
Body: { "student": "...", "mark": 75, ... }

✅ Success if user.has_privilege(GRADING_ENTER)
❌ 403 Forbidden if not a teacher
❌ 403 Forbidden if GRADING_ENTER not in privileges
```

### Approve Grades (privilege + role check)
```
POST /api/v2/gradebooks/123/approve/
Headers: Authorization: Bearer {token}

✅ Success if user.role IN [ADMIN, SUPERADMIN]
✅ Success if user.has_privilege(GRADING_APPROVE)
❌ 403 Forbidden if only GRADING_ENTER
```

## Troubleshooting

### "User doesn't have privilege X"
1. Check `user.role` - does it default include privilege?
2. Check `SpecialPrivilege.objects.filter(user=user, code='X')`
3. Check `RoleDefaultPrivilege.objects.filter(role=user.role, privilege_code='X')`
4. Check expiration: `SpecialPrivilege.expires_at < now()`

### "Parent can't see children"
1. Check `ParentAccount.objects.filter(user=parent_user)` exists
2. Check `StudentGuardian` records match parent email
3. Check parent_account.parent_email matches StudentGuardian.email
4. Verify guardian → student relationship exists

### "Student can't see own record"
1. Check `StudentAccount.objects.filter(user=student_user)` exists
2. Check `StudentAccount.student_id` matches actual Student.id_number
3. Verify student_account.user == request.user
4. Verify user.has_privilege("STUDENTS_VIEW")

## Admin Actions

### Grant Temporary Privilege
1. Go to Django Admin → Special Privileges → Add
2. Select user
3. Enter privilege code
4. Set expires_at to tomorrow → auto-revokes
5. Add notes: "Temporary approval for Q3 grading period"

### Revoke A Privilege
1. Go to Django Admin → Special Privileges
2. Click on grant
3. Delete
4. Privilege auto-removed next request

### Check User's All Privileges
```python
from users.models import User
user = User.objects.get(id_number='...')
print(user.get_privileges())
# Output: ['GRADING_ENTER', 'STUDENTS_VIEW', 'GRADING_APPROVE', ...]
```

### Create Account Link
```python
from users.models import StudentAccount, User, Student
user = User.objects.get(email='student@school.com')
student = Student.objects.get(id_number='001234')
StudentAccount.objects.create(
    user=user,
    student_id='001234'
)
# Now accessible via: user.student_account.student_id
```

---

Complete permissions flow diagram in AUTH_IMPLEMENTATION_PLAN.md
Detailed implementation guide in AUTH_BACKEND_IMPLEMENTATION.md

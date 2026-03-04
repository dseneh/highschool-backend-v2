# Access Policy Quick Reference

## 1. Adding Policy to a New View

### For APIView
```python
from academics.access_policies import AcademicsAccessPolicy

class MyNewView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    
    def get(self, request):
        # Your logic here
        pass
```

### For ViewSet
```python
from staff.access_policies import StaffAccessPolicy

class MyModelViewSet(viewsets.ModelViewSet):
    permission_classes = [StaffAccessPolicy]
    queryset = MyModel.objects.all()
    serializer_class = MySerializer
```

## 2. Common Policy Patterns

### Basic CRUD with Role Checks
```python
statements = [
    # Admin gets everything
    {
        "action": ["*"],
        "principal": "authenticated",
        "effect": "allow",
        "condition": "is_role_in:admin,superadmin",
    },
    
    # Specific roles get CRUD (no delete)
    {
        "action": ["list", "retrieve", "create", "update", "partial_update"],
        "principal": "authenticated",
        "effect": "allow",
        "condition": "is_role_in:registrar,accountant",
    },
    
    # Everyone can read
    {
        "action": ["list", "retrieve"],
        "principal": "authenticated",
        "effect": "allow",
        "condition": "is_role_in:viewer,teacher,student",
    },
]
```

### Using Privilege Checks
```python
statements = [
    # Privilege for destructive actions
    {
        "action": ["destroy"],
        "principal": "authenticated",
        "effect": "allow",
        "condition": "has_privilege:DOMAIN_DELETE",
    },
    
    # Multiple privileges (any match = allow)
    {
        "action": ["update", "partial_update"],
        "principal": "authenticated",
        "effect": "allow",
        "condition": "has_any_privilege:DOMAIN_EDIT,DOMAIN_MANAGE",
    },
]
```

### Custom Actions
```python
statements = [
    # Custom action in viewset
    {
        "action": ["approve", "set_status"],
        "principal": "authenticated",
        "effect": "allow",
        "condition": "has_privilege:GRADING_APPROVE",
    },
]
```

## 3. Available Conditions

### Role Checks
```python
"condition": "is_role_in:admin,superadmin"           # Multiple roles (OR logic)
"condition": "is_role_in:teacher"                     # Single role
```

**Available Roles:**
- `superadmin` - System super admin
- `admin` - School admin
- `registrar` - School registrar
- `accountant` - Finance officer
- `teacher` - Teaching staff
- `student` - Student user
- `parent` - Parent/guardian
- `viewer` - Read-only user
- `data_entry` - Data entry clerk

### Privilege Checks
```python
"condition": "has_privilege:GRADING_APPROVE"          # Single privilege
"condition": "has_any_privilege:EDIT,MANAGE"         # Multiple (OR logic)
```

**Common Privileges:**

**Core/Academics:**
- `CORE_VIEW` - View academic configuration
- `CORE_MANAGE` - Manage academic configuration

**Students:**
- `STUDENTS_VIEW` - View students
- `STUDENTS_MANAGE` - Manage students
- `STUDENT_ENROLL` - Enroll students
- `STUDENT_EDIT` - Edit student records
- `STUDENT_DELETE` - Delete students

**Grading:**
- `GRADING_VIEW` - View grades
- `GRADING_MANAGE` - Manage grading configuration
- `GRADING_ENTER` - Enter grades
- `GRADING_REVIEW` - Review grades
- `GRADING_APPROVE` - Approve grades
- `GRADING_REJECT` - Reject grades

**Finance:**
- `FINANCE_VIEW` - View finance data
- `FINANCE_MANAGE` - Manage finance configuration
- `TRANSACTION_CREATE` - Create transactions
- `TRANSACTION_UPDATE` - Update transactions
- `TRANSACTION_DELETE` - Delete transactions
- `TRANSACTION_APPROVE` - Approve transactions
- `TRANSACTION_CANCEL` - Cancel transactions

**Settings:**
- `SETTINGS_GRADING_MANAGE` - Manage grading settings

### Principal Types
```python
"principal": "authenticated"   # Logged-in users
"principal": "anonymous"       # Not logged in
"principal": "*"               # Anyone (use carefully!)
```

### Effect
```python
"effect": "allow"   # Grant access
"effect": "deny"    # Deny access (default if no match)
```

## 4. Testing Privileges in Django Shell

```python
from users.models import User, SpecialPrivilege
from common.status import Roles

# Get user
teacher = User.objects.get(email='teacher@school.com')

# Check privilege (checks role defaults + special grants)
teacher.has_privilege("GRADING_ENTER")        # True/False
teacher.has_privilege("grading_enter")        # Case insensitive

# Get all privileges
teacher.get_privileges()                      # ["GRADING_ENTER", "STUDENTS_VIEW", ...]

# Grant special privilege
admin = User.objects.get(role=Roles.ADMIN)
SpecialPrivilege.objects.create(
    user=teacher,
    code="GRADING_APPROVE",
    granted_by=admin,
    notes="Q3 grading period approval"
)

# Now teacher.has_privilege("GRADING_APPROVE") returns True

# Grant with expiration
from django.utils import timezone
from datetime import timedelta

SpecialPrivilege.objects.create(
    user=teacher,
    code="GRADING_APPROVE",
    granted_by=admin,
    expires_at=timezone.now() + timedelta(days=30),
    notes="Temporary approval for Q3"
)
```

## 5. Debugging Access Denied

### Check Policy Statements
```python
from students.access_policies import StudentAccessPolicy

# View all statements
for stmt in StudentAccessPolicy.statements:
    print(stmt)
```

### Test Condition Manually
```python
from rest_framework.test import APIRequestFactory
from students.access_policies import StudentAccessPolicy

factory = APIRequestFactory()
request = factory.get('/')
request.user = teacher

policy = StudentAccessPolicy()
# Test specific condition
result = policy.has_privilege(request, None, 'list', 'STUDENTS_VIEW')
print(f"has_privilege result: {result}")
```

### Check User Privileges
```python
user = User.objects.get(email='user@school.com')
print(f"Role: {user.role}")
print(f"Privileges: {user.get_privileges()}")
print(f"Has STUDENTS_VIEW: {user.has_privilege('STUDENTS_VIEW')}")
```

### Check Role Default Privileges
```python
from users.models import RoleDefaultPrivilege

# See what privileges a role gets by default
teacher_privs = RoleDefaultPrivilege.objects.filter(role='teacher')
for priv in teacher_privs:
    print(f"  - {priv.privilege_code}")
```

## 6. Common Issues & Solutions

### Issue: User should have access but gets 403
**Cause:** Privilege code case mismatch or missing role default

**Solution:**
```python
# Check privilege codes are uppercase
user.has_privilege("GRADING_ENTER")  # ✅ Correct
user.has_privilege("grading_enter")  # ⚠ Will be normalized but check migration

# Verify role default exists
RoleDefaultPrivilege.objects.filter(role=user.role, privilege_code="GRADING_ENTER")
```

### Issue: Policy statements not being evaluated
**Cause:** Missing `permission_classes` on view

**Solution:**
```python
class MyView(APIView):
    permission_classes = [MyAccessPolicy]  # ✅ Add this
```

### Issue: All users getting access or none getting access
**Cause:** Incorrect action name in statements

**Solution:**
```python
# Match the actual HTTP method/action name
{
    "action": ["list", "retrieve"],  # ✅ For GET on list/detail
    "action": ["create"],            # ✅ For POST
    "action": ["update", "partial_update"],  # ✅ For PUT/PATCH
    "action": ["destroy"],           # ✅ For DELETE
}
```

## 7. Adding Custom Conditions

```python
class MyAccessPolicy(BaseSchoolAccessPolicy):
    statements = [
        {
            "action": ["retrieve"],
            "principal": "authenticated",
            "effect": "allow",
            "condition": "is_own_record",  # Custom condition
        },
    ]
    
    def is_own_record(self, request, view, action) -> bool:
        """Check if user is accessing their own record"""
        user = self._get_user(request)
        if not user:
            return False
        
        # Get record ID from URL
        record_id = view.kwargs.get('pk')
        
        # Your custom logic here
        return str(user.id) == str(record_id)
```

## 8. Migration Commands

```bash
# Create privilege models
python manage.py migrate users 0002_add_privilege_models

# Populate role privileges
python manage.py migrate users 0003_populate_role_privileges

# Check migrations
python manage.py showmigrations users

# Validate setup
python scripts/validate_access_policies.py
```

## 9. Production Checklist

- [ ] All migrations applied
- [ ] RoleDefaultPrivilege populated (40+ entries)
- [ ] All views have `permission_classes` set
- [ ] Privilege codes use uppercase consistently
- [ ] Test each role can access appropriate endpoints
- [ ] Test privilege grants/revokes work
- [ ] Test expired privileges are ignored
- [ ] Audit logs capture privilege changes

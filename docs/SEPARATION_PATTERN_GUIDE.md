# Business Logic Separation Pattern - Quick Reference

## ✅ Auth & Students Modules Complete!

This guide shows how to apply the same pattern to remaining modules.

---

## Pattern Overview

### 3 Layers
```
1. Business Logic (Pure Python)
   ├── service.py - Business rules & validation
   ├── models.py - Data transfer objects (dataclasses)
   └── Pure Python, no framework imports

2. Adapter Layer (Framework-Specific)
   ├── django_adapter.py - Database operations
   ├── fastapi_adapter.py (future)
   └── Converts between framework models and business objects

3. View/Presentation Layer
   ├── views.py - HTTP handling
   ├── Thin layer calling business + adapter
   └── Framework-specific (Django, FastAPI, etc.)
```

---

## Step-by-Step Guide

### Step 1: Create Business Models (Data Transfer Objects)

**File**: `business/<module>/<module>_models.py`

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class FeatureData:
    """Framework-agnostic data representation"""
    id: str
    name: str
    status: str
    created_by: Optional[str] = None
    # Add all fields you need
```

**Rules:**
- ✅ Use dataclasses (Python 3.7+)
- ✅ Only basic Python types (str, int, bool, etc.)
- ✅ No Django/framework imports
- ✅ Optional fields should have defaults

---

### Step 2: Create Business Service (Business Logic)

**File**: `business/<module>/<module>_service.py`

```python
from typing import Optional, Tuple, List
from .<module>_models import FeatureData

# Validation Functions
def validate_feature_creation(data: dict) -> Tuple[bool, List[str]]:
    """
    Validate feature creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not data.get('name'):
        errors.append("Name is required")
    
    if data.get('status') not in ['active', 'inactive']:
        errors.append("Invalid status")
    
    return len(errors) == 0, errors


# Business Rules
def can_delete_feature(feature_data: FeatureData, has_dependencies: bool) -> Tuple[bool, Optional[str]]:
    """
    Business rule: Can this feature be deleted?
    
    Returns:
        (can_delete, error_message_if_not)
    """
    if has_dependencies:
        return False, "Cannot delete feature with dependencies"
    
    return True, None


# Data Preparation
def prepare_feature_for_creation(raw_data: dict) -> dict:
    """
    Prepare and clean data for creation
    """
    return {
        'name': raw_data.get('name', '').strip(),
        'status': raw_data.get('status', 'active').lower(),
        # Transform data as needed
    }
```

**Rules:**
- ✅ Only pure Python functions
- ✅ No Django/framework imports
- ✅ Return tuples for validation: `(success, error)`
- ✅ Use type hints
- ✅ Keep functions small and focused

---

### Step 3: Create Django Adapter (Database Operations)

**File**: `business/<module>/django_adapter.py`

```python
from typing import Optional
from django.db import transaction
from myapp.models import Feature  # Django model import HERE ONLY
from .<module>_models import FeatureData

# Conversion Functions
def django_feature_to_data(feature) -> FeatureData:
    """Convert Django model to business data object"""
    return FeatureData(
        id=str(feature.id),
        name=feature.name,
        status=feature.status,
        created_by=str(feature.created_by.id) if feature.created_by else None,
    )


def data_to_django_feature(data: FeatureData, feature=None):
    """Convert business data to Django model"""
    if feature is None:
        feature = Feature()
    
    feature.name = data.name
    feature.status = data.status
    # Map other fields
    
    return feature


# Database Operations
@transaction.atomic
def create_feature_in_db(data: dict, school_id: str) -> Feature:
    """Create feature in database"""
    feature = Feature.objects.create(
        school_id=school_id,
        **data
    )
    return feature


def update_feature_in_db(feature_id: str, data: dict) -> Optional[Feature]:
    """Update feature in database"""
    try:
        feature = Feature.objects.get(id=feature_id)
        for key, value in data.items():
            setattr(feature, key, value)
        feature.save()
        return feature
    except Feature.DoesNotExist:
        return None


def delete_feature_from_db(feature_id: str) -> bool:
    """Delete feature from database"""
    try:
        Feature.objects.get(id=feature_id).delete()
        return True
    except Feature.DoesNotExist:
        return False


def feature_has_dependencies(feature_id: str) -> bool:
    """Check if feature has dependencies"""
    feature = Feature.objects.filter(id=feature_id).first()
    if not feature:
        return False
    
    # Check related objects
    return feature.related_items.exists()
```

**Rules:**
- ✅ Only Django imports in this file
- ✅ All database operations go here
- ✅ Use transactions for complex operations
- ✅ Return Django models or basic types
- ✅ Keep functions focused on database

---

### Step 4: Update Django Views

**File**: `<module>/views/<module>.py`

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

# Import business logic (framework-agnostic)
from business.<module> import <module>_service
from business.<module>.django_adapter import (
    create_feature_in_db,
    update_feature_in_db,
    delete_feature_from_db,
    django_feature_to_data,
    feature_has_dependencies,
)

class FeatureView(APIView):
    def post(self, request, school_id):
        """Create feature - thin view calling business logic"""
        
        # 1. Validate using business logic
        is_valid, errors = <module>_service.validate_feature_creation(request.data)
        if not is_valid:
            return Response({"errors": errors}, status=400)
        
        # 2. Prepare data using business logic
        prepared_data = <module>_service.prepare_feature_for_creation(request.data)
        
        # 3. Create using adapter (database operation)
        feature = create_feature_in_db(prepared_data, school_id)
        
        # 4. Return response
        return Response(FeatureSerializer(feature).data, status=201)
    
    def put(self, request, school_id, feature_id):
        """Update feature"""
        
        # Validate
        is_valid, errors = <module>_service.validate_feature_update(request.data)
        if not is_valid:
            return Response({"errors": errors}, status=400)
        
        # Update
        feature = update_feature_in_db(feature_id, request.data)
        if not feature:
            return Response({"error": "Not found"}, status=404)
        
        return Response(FeatureSerializer(feature).data)
    
    def delete(self, request, school_id, feature_id):
        """Delete feature"""
        
        # Get feature data
        feature = Feature.objects.filter(id=feature_id).first()
        if not feature:
            return Response({"error": "Not found"}, status=404)
        
        feature_data = django_feature_to_data(feature)
        
        # Check business rules
        can_delete, error = <module>_service.can_delete_feature(
            feature_data,
            has_dependencies=feature_has_dependencies(feature_id)
        )
        
        if not can_delete:
            return Response({"error": error}, status=400)
        
        # Delete
        delete_feature_from_db(feature_id)
        return Response(status=204)
```

**Rules:**
- ✅ Keep views thin (10-30 lines per method)
- ✅ Only HTTP concerns in views
- ✅ Call business logic for validation/rules
- ✅ Call adapters for database operations
- ✅ No business logic in views

---

## Common Patterns

### Pattern 1: Validation
```python
# Business logic
def validate_feature(data: dict) -> Tuple[bool, List[str]]:
    errors = []
    if not data.get('name'):
        errors.append("Name required")
    return len(errors) == 0, errors

# View
is_valid, errors = service.validate_feature(request.data)
if not is_valid:
    return Response({"errors": errors}, 400)
```

### Pattern 2: Business Rules
```python
# Business logic
def can_perform_action(user_role: str, target_status: str) -> Tuple[bool, str]:
    if user_role == 'VIEWER' and target_status == 'deleted':
        return False, "Viewers cannot delete"
    return True, None

# View
can_do, error = service.can_perform_action(user.role, 'deleted')
if not can_do:
    return Response({"error": error}, 403)
```

### Pattern 3: Data Transformation
```python
# Business logic
def prepare_data(raw: dict) -> dict:
    return {
        'name': raw.get('name', '').strip().title(),
        'status': raw.get('status', 'active').lower(),
    }

# View
clean_data = service.prepare_data(request.data)
obj = adapter.create_in_db(clean_data)
```

### Pattern 4: Complex Queries/Filters
```python
# Business logic
def parse_filters(params: dict) -> dict:
    """Parse query parameters into filter criteria"""
    filters = {}
    if params.get('status'):
        filters['status__in'] = params['status'].split(',')
    return filters

# View
filters = service.parse_filters(request.query_params)
queryset = Model.objects.filter(**filters)
```

---

## Testing Pattern

### Test Business Logic (No Django)
```python
# tests/test_<module>_business.py
from business.<module> import <module>_service

def test_validation():
    """Test without any Django/database"""
    is_valid, errors = <module>_service.validate_feature_creation({
        'name': '',  # Invalid
    })
    
    assert not is_valid
    assert 'Name is required' in errors
```

### Test Django Integration
```python
# tests/test_<module>_integration.py
from django.test import TestCase
from business.<module>.django_adapter import create_feature_in_db

class FeatureIntegrationTest(TestCase):
    def test_create_feature(self):
        """Test with Django database"""
        feature = create_feature_in_db({
            'name': 'Test',
            'status': 'active',
        }, school_id='123')
        
        self.assertIsNotNone(feature)
        self.assertEqual(feature.name, 'Test')
```

---

## Checklist for New Module

- [ ] Create `business/<module>/` directory
- [ ] Create `<module>_models.py` with dataclasses
- [ ] Create `<module>_service.py` with business functions
- [ ] Create `django_adapter.py` with database operations
- [ ] Update Django views to use business logic
- [ ] Write business logic tests (no Django)
- [ ] Write integration tests (with Django)
- [ ] Document what changed

---

## Real Examples from Completed Modules

### Students Module
- ✅ `business/students/student_models.py` - StudentData dataclass
- ✅ `business/students/student_service.py` - 21 business functions
- ✅ `business/students/django_adapter.py` - Database operations
- ✅ `students/views/student.py` - Thin views using business logic

### Users Module
- ✅ `business/users/user_models.py` - UserData, LoginCredentials
- ✅ `business/users/user_service.py` - 24 business functions
- ✅ `users/views/user.py` - CRUD using business logic
- ✅ `users/views/auth.py` - Authentication using business logic

---

## Benefits

### ✅ Framework Migration
Same business logic works with:
- Django (current)
- FastAPI (just create fastapi_adapter.py)
- Flask (just create flask_adapter.py)
- Any Python framework

### ✅ Testing
- Test business logic without database
- Test integration separately
- Faster tests (business logic doesn't need Django)

### ✅ Maintainability
- Business rules in one place
- Easier to find and update
- Clear separation of concerns

### ✅ Reusability
- Use same logic in API, CLI, background jobs
- Share logic across different endpoints
- No code duplication

---

## Next Modules to Separate

1. **Finance** - Fee management, billing
2. **Grading** - Grade calculation, reports
3. **Staff** - Staff management
4. **Reports** - Report generation

Apply the same pattern to each! 🚀

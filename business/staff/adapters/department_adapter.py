"""
Department Django Adapter - Database Operations

This module handles all Django-specific database operations for departments.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional
import re
from django.db import transaction
from django.db.models import Q

from staff.models import Department
from business.staff.staff_models import DepartmentData


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_department_to_data(department) -> DepartmentData:
    """Convert Django Department model to business data object"""
    return DepartmentData(
        id=str(department.id),
        name=department.name,
        code=department.code or "",
        description=department.description or None,
    )


# =============================================================================
# DEPARTMENT DATABASE OPERATIONS
# =============================================================================

@transaction.atomic
def create_department_in_db(data: dict, user=None) -> Department:
    """Create department in database"""
    code = data.get("code") or ""
    if not code.strip():
        code = _generate_department_code(data["name"])

    department = Department.objects.create(
        name=data['name'],
        code=code,
        description=data.get('description'),
        created_by=user,
        updated_by=user,
    )
    
    return department


def update_department_in_db(department_id: str, data: dict, user=None) -> Optional[Department]:
    """Update department in database"""
    try:
        department = Department.objects.get(id=department_id)
        
        for field, value in data.items():
            if hasattr(department, field) and field not in ['id', 'created_at', 'created_by']:
                setattr(department, field, value)
        
        department.updated_by = user
        department.save()
        
        return department
    except Department.DoesNotExist:
        return None


def delete_department_from_db(department_id: str) -> bool:
    """Delete department from database"""
    try:
        Department.objects.get(id=department_id).delete()
        return True
    except Department.DoesNotExist:
        return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def department_has_staff(department_id: str) -> bool:
    """Check if department has staff assigned"""
    try:
        department = Department.objects.get(id=department_id)
        return hasattr(department, 'staff_set') and department.staff_set.exists()
    except Department.DoesNotExist:
        return False


def department_has_positions(department_id: str) -> bool:
    """Check if department has positions assigned"""
    try:
        department = Department.objects.get(id=department_id)
        return hasattr(department, 'position_set') and department.position_set.exists()
    except Department.DoesNotExist:
        return False


def _generate_department_code(name: str) -> str:
    """Generate a unique department code from name."""
    words = re.findall(r"\b\w", name or "")
    base_code = "".join(words).upper()[:25]

    if not base_code:
        base_code = "DEPT"

    code = base_code
    counter = 1
    while True:
        lookup = Q(code=code)
        if not Department.objects.filter(lookup).exists():
            break

        suffix = str(counter)
        max_base_length = 30 - len(suffix)
        code = base_code[:max_base_length] + suffix
        counter += 1

        if counter > 9999:
            import time

            code = f"DEPT{int(time.time()) % 100000}"
            break

    return code

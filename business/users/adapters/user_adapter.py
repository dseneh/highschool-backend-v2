"""
User Django Adapter - Database Operations

This module handles all Django-specific database operations for users.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional

from users.models import CustomUser
from business.users.user_models import UserData


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_user_to_data(user: CustomUser) -> UserData:
    """Convert Django User model to plain data object"""
    return UserData(
        id=str(user.id),
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        gender=user.gender,
        id_number=user.id_number,
        role=user.role,
        status=user.status,
        account_type=user.account_type,
        school_id=str(user.school_id) if user.school_id else None,
        is_staff=user.is_staff,
        is_superuser=user.is_superuser,
        is_active=user.is_active,
        is_default_password=user.is_default_password,
        special_privileges=list(user.special_privileges.values_list('code', flat=True)) if hasattr(user, 'special_privileges') else [],
        last_login=user.last_login,
        photo=user.photo.url if user.photo else None,
    )


def data_to_django_user(data: dict, user: Optional[CustomUser] = None) -> CustomUser:
    """Update Django User model from data dict"""
    if user is None:
        user = CustomUser()
    
    # Update fields
    if 'username' in data:
        user.username = data['username']
    if 'email' in data:
        user.email = data['email']
    if 'first_name' in data:
        user.first_name = data['first_name']
    if 'last_name' in data:
        user.last_name = data['last_name']
    if 'gender' in data:
        user.gender = data['gender']
    if 'id_number' in data:
        user.id_number = data['id_number']
    if 'role' in data:
        user.role = data['role']
    if 'status' in data:
        user.status = data['status']
    if 'account_type' in data:
        user.account_type = data['account_type']
    if 'school_id' in data:
        user.school_id = data['school_id']
    if 'is_staff' in data:
        user.is_staff = data['is_staff']
    if 'is_superuser' in data:
        user.is_superuser = data['is_superuser']
    if 'is_active' in data:
        user.is_active = data['is_active']
    
    return user


# =============================================================================
# USER DATABASE OPERATIONS
# =============================================================================

def create_user_in_db(data: dict) -> CustomUser:
    """Create user in database"""
    user = CustomUser.objects.create_user(
        username=data['username'],
        email=data.get('email'),
        password=data.get('password'),
        first_name=data.get('first_name', ''),
        last_name=data.get('last_name', ''),
        gender=data.get('gender'),
        id_number=data.get('id_number'),
        role=data.get('role'),
        status=data.get('status', 'active'),
        account_type=data.get('account_type'),
        school_id=data.get('school_id'),
    )
    return user


def update_user_in_db(user: CustomUser, data: dict) -> CustomUser:
    """Update user in database"""
    for field, value in data.items():
        if hasattr(user, field) and field not in ['id', 'password']:
            setattr(user, field, value)
    
    user.save()
    return user


def delete_user_from_db(user: CustomUser) -> bool:
    """Delete user from database"""
    try:
        user.delete()
        return True
    except Exception:
        return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_user_by_username(username: str) -> Optional[CustomUser]:
    """Get user by username"""
    try:
        return CustomUser.objects.get(username=username)
    except CustomUser.DoesNotExist:
        return None


def get_user_by_email(email: str) -> Optional[CustomUser]:
    """Get user by email"""
    try:
        return CustomUser.objects.get(email=email)
    except CustomUser.DoesNotExist:
        return None


def check_username_exists(username: str, exclude_id: Optional[str] = None) -> bool:
    """Check if username exists"""
    queryset = CustomUser.objects.filter(username=username)
    if exclude_id:
        queryset = queryset.exclude(id=exclude_id)
    return queryset.exists()


def check_email_exists(email: str, exclude_id: Optional[str] = None) -> bool:
    """Check if email exists"""
    queryset = CustomUser.objects.filter(email=email)
    if exclude_id:
        queryset = queryset.exclude(id=exclude_id)
    return queryset.exists()

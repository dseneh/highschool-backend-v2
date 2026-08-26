"""
User Django Adapter - Database Operations

This module handles all Django-specific database operations for users.
Business logic should NOT be in this file - only database interactions.
"""

from typing import Optional

from users.models import User
from business.users.user_models import UserData


# =============================================================================
# DATA CONVERSION FUNCTIONS
# =============================================================================

def django_user_to_data(user: User) -> UserData:
    """Convert Django User model to plain data object"""
    return UserData(
        id=str(user.id),
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        gender=user.gender,
        id_number=user.id_number,
        status=user.status,
        account_type=user.account_type,
        is_platform_superuser=user.is_platform_superuser,
        is_active=user.is_active,
        is_default_password=user.is_default_password,
        last_login=user.last_login,
        photo=user.photo.url if user.photo else None,
    )


def data_to_django_user(data: dict, user: Optional[User] = None) -> User:
    """Update Django User model from data dict"""
    if user is None:
        user = User()
    
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
    if 'status' in data:
        user.status = data['status']
    if 'account_type' in data:
        user.account_type = data['account_type']
    if 'is_platform_superuser' in data:
        user.is_platform_superuser = data['is_platform_superuser']
    if 'is_active' in data:
        user.is_active = data['is_active']
    
    return user


# =============================================================================
# USER DATABASE OPERATIONS
# =============================================================================

def create_user_in_db(data: dict) -> User:
    """Create user in database"""
    user = User.objects.create_user(
        username=data['username'],
        email=data.get('email'),
        password=data.get('password'),
        first_name=data.get('first_name', ''),
        last_name=data.get('last_name', ''),
        gender=data.get('gender'),
        id_number=data.get('id_number'),
        status=data.get('status', 'active'),
        account_type=data.get('account_type'),
        is_platform_superuser=data.get('is_platform_superuser', False),
    )
    return user


def update_user_in_db(user: User, data: dict) -> User:
    """Update user in database"""
    for field, value in data.items():
        if hasattr(user, field) and field not in ['id', 'password']:
            setattr(user, field, value)
    
    user.save()
    return user


def delete_user_from_db(user: User) -> bool:
    """Delete user from database"""
    try:
        user.delete()
        return True
    except Exception:
        return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_user_by_username(username: str) -> Optional[User]:
    """Get user by username"""
    try:
        return User.objects.get(username=username)
    except User.DoesNotExist:
        return None


def get_user_by_email(email: str) -> Optional[User]:
    """Get user by email"""
    try:
        return User.objects.get(email=email)
    except User.DoesNotExist:
        return None


def check_username_exists(username: str, exclude_id: Optional[str] = None) -> bool:
    """Check if username exists"""
    queryset = User.objects.filter(username=username)
    if exclude_id:
        queryset = queryset.exclude(id=exclude_id)
    return queryset.exists()


def check_email_exists(email: str, exclude_id: Optional[str] = None) -> bool:
    """Check if email exists"""
    queryset = User.objects.filter(email=email)
    if exclude_id:
        queryset = queryset.exclude(id=exclude_id)
    return queryset.exists()

"""
User business logic - Pure Python functions (no Django dependencies)
"""
from typing import Optional, List
from business.users.user_models import UserData, LoginCredentials, LoginResult


def validate_username(username: str) -> tuple[Optional[str], Optional[str]]:
    """
    Validate username according to rules:
    - Should not start with numbers
    - Only letters, numbers, and dots allowed
    - Maximum 15 characters
    - Convert to lowercase
    
    Returns: (validated_username, error_message)
    """
    if not username:
        return None, "Username is required."
    
    # Convert to lowercase
    username = username.lower()
    
    # Check length
    if len(username) > 15:
        return None, "Username cannot exceed 15 characters."
    
    # Check if starts with number
    if username[0].isdigit():
        return None, "Username cannot start with a number."
    
    # Check allowed characters (letters, numbers, dots)
    import re
    if not re.match(r'^[a-z0-9.]+$', username):
        return None, "Username can only contain letters, numbers, and dots."
    
    return username, None


def validate_login_credentials(credentials: LoginCredentials) -> Optional[str]:
    """
    Validate login credentials format
    Returns error message if invalid, None if valid
    """
    if not credentials.identifier:
        return "Identifier (username/email/ID) is required"
    
    if not credentials.password:
        return "Password is required"
    
    if len(credentials.password) < 4:
        return "Password must be at least 4 characters"
    
    return None


def can_user_authenticate(user: UserData) -> tuple[bool, Optional[str]]:
    """
    Check if user is allowed to authenticate
    Returns: (can_auth, error_message)
    """
    if not user.is_active:
        return False, "Account is inactive"
    
    if user.status and user.status.lower() in ['suspended', 'disabled', 'banned']:
        return False, f"Account is {user.status}"
    
    return True, None


def validate_user_data(data: dict) -> List[str]:
    """
    Validate user data for creation/update
    Returns list of error messages
    """
    errors = []
    
    # Required fields
    if not data.get('username'):
        errors.append("Username is required")
    elif len(data['username']) > 15:
        errors.append("Username cannot exceed 15 characters")
    
    if not data.get('email'):
        errors.append("Email is required")
    
    if not data.get('first_name'):
        errors.append("First name is required")
    
    if not data.get('last_name'):
        errors.append("Last name is required")
    
    # Validate gender
    if data.get('gender') and data['gender'] not in ['male', 'female', 'M', 'F']:
        errors.append("Gender must be 'male' or 'female'")
    
    return errors


def get_user_full_name(user: UserData) -> str:
    """Get user's full name"""
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    return user.first_name or user.last_name or user.username


def is_system_admin(user: UserData) -> bool:
    """Check if user is a system administrator"""
    return user.is_superuser or user.role == 'admin'


def filter_users_by_criteria(
    users: List[UserData],
    role: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None
) -> List[UserData]:
    """
    Filter users by various criteria (for in-memory filtering)
    """
    filtered = users
    
    if role:
        filtered = [u for u in filtered if u.role == role]
    
    if status:
        filtered = [u for u in filtered if u.status == status]
    
    if search:
        search_lower = search.lower()
        filtered = [
            u for u in filtered
            if (search_lower in (u.username or '').lower() or
                search_lower in (u.email or '').lower() or
                search_lower in (u.first_name or '').lower() or
                search_lower in (u.last_name or '').lower())
        ]
    
    return filtered


def authenticate_user(identifier: str, password: str, user_data: Optional[UserData] = None) -> tuple[bool, Optional[str]]:
    """
    Business logic for user authentication
    
    Args:
        identifier: username, email, or id_number
        password: plain password (will be verified by infrastructure)
        user_data: user data if already fetched
        
    Returns:
        (success, error_message)
    """
    if not identifier or not password:
        return False, "Username and password are required"
    
    if not user_data:
        return False, "Invalid credentials, no user found"
    
    # Check account status
    allowed_statuses = ['active', 'reset', 'created']
    if user_data.status and user_data.status.lower() not in allowed_statuses:
        return False, f"User account is {user_data.status}. Please contact the admin for assistance."
    
    # Password verification happens in infrastructure layer
    return True, None


def should_update_status_on_login(current_status: str) -> tuple[bool, str]:
    """
    Business rule: Should we update user status after successful login?
    
    Returns:
        (should_update, new_status)
    """
    if current_status.lower() in ['reset', 'created']:
        return True, 'active'
    return False, current_status


def validate_password_reset_request(email: str, id_number: str) -> tuple[bool, Optional[str]]:
    """
    Validate password reset request data
    
    Returns:
        (is_valid, error_message)
    """
    if not email:
        return False, "Email is required"
    
    if not id_number:
        return False, "ID number is required"
    
    # Basic email format validation
    if '@' not in email or '.' not in email:
        return False, "Invalid email format"
    
    return True, None


def can_reset_password(user_data: UserData) -> tuple[bool, Optional[str]]:
    """
    Business rule: Can this user reset their password?
    
    Returns:
        (can_reset, error_message)
    """
    # Users without a school (except admins) can't reset
    if not user_data.school_id and user_data.role not in ['systemadmin', 'admin']:
        return False, "User account is not properly configured. Please contact support."
    
    # Inactive users can't reset
    if not user_data.is_active:
        return False, "Account is inactive. Please contact support."
    
    return True, None


def validate_password_change(old_password: str, new_password: str, confirm_password: Optional[str] = None) -> tuple[bool, list[str]]:
    """
    Validate password change request
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not new_password:
        errors.append("New password is required")
    
    if len(new_password) < 4:
        errors.append("Password must be at least 4 characters")
    
    if confirm_password and new_password != confirm_password:
        errors.append("Passwords do not match")
    
    # Could add more rules:
    # - Must contain uppercase
    # - Must contain number
    # - Must contain special character
    
    return len(errors) == 0, errors


def validate_user_creation_data(data: dict) -> tuple[bool, list[str]]:
    """
    Validate user creation data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    # Required fields
    if not data.get('account_type'):
        errors.append("Account type is required.")
    
    valid_account_types = ['student', 'parent', 'teacher', 'staff', 'admin', 'user']
    if data.get('account_type') and data['account_type'] not in valid_account_types:
        errors.append(f"Invalid account type. Must be one of: {', '.join(valid_account_types)}")
    
    # Role validation
    account_type = data.get('account_type')
    if account_type not in ['student', 'parent'] and not data.get('role'):
        errors.append("Role is required for this account type.")
    
    # ID number validation
    if not data.get('id_number'):
        errors.append("ID number is required.")
    
    # Name validation
    if not data.get('first_name'):
        errors.append("First name is required.")
    
    if not data.get('last_name'):
        errors.append("Last name is required.")
    
    # Email validation
    if data.get('email'):
        email = data['email']
        if '@' not in email or '.' not in email:
            errors.append("Invalid email format.")
    
    return len(errors) == 0, errors


def get_role_for_account_type(account_type: str, provided_role: Optional[str] = None) -> str:
    """
    Business rule: Map account type to role
    
    Args:
        account_type: The account type
        provided_role: Role explicitly provided (optional)
        
    Returns:
        The role to use
    """
    # Auto-map for students and parents
    if account_type in ['student', 'parent']:
        return account_type
    
    # Use provided role for others
    return provided_role or 'viewer'


def should_auto_generate_username(username: Optional[str], id_number: str) -> tuple[bool, str]:
    """
    Business rule: Should we auto-generate username?
    
    Returns:
        (should_generate, username_to_use)
    """
    if not username or not username.strip():
        # Auto-generate from id_number
        return True, id_number.lower()
    
    return False, username


def validate_user_update_data(current_user: UserData, update_data: dict) -> tuple[bool, list[str]]:
    """
    Validate user update data
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    # Immutable fields
    immutable_fields = ['id_number']
    for field in immutable_fields:
        if field in update_data and update_data[field] != getattr(current_user, field, None):
            errors.append(f"Cannot change {field} after creation")
    
    # Email validation if being updated
    if 'email' in update_data and update_data['email']:
        email = update_data['email']
        if '@' not in email or '.' not in email:
            errors.append("Invalid email format")
    
    return len(errors) == 0, errors


def can_delete_user(user_data: UserData, has_created_records: bool = False, is_self_deletion: bool = False) -> tuple[bool, Optional[str]]:
    """
    Business rule: Can a user be deleted?
    
    Args:
        user_data: User to check
        has_created_records: Does user have created/modified records?
        is_self_deletion: Is the user trying to delete themselves?
        
    Returns:
        (can_delete, reason_if_not)
    """
    if is_self_deletion:
        return False, "You cannot delete yourself"
    
    # System admins typically shouldn't be deleted
    if user_data.is_superuser:
        return False, "Cannot delete superuser accounts"
    
    # Users with created records might have data integrity issues
    if has_created_records:
        return False, "Cannot delete user with associated records. Consider deactivating instead."
    
    return True, None


def should_allow_own_profile_field_update(field_name: str, user_role: str, is_own_profile: bool) -> bool:
    """
    Business rule: Can a user update a specific field on their own profile?
    
    Args:
        field_name: Field being updated
        user_role: Role of the user
        is_own_profile: Is this their own profile?
        
    Returns:
        True if allowed, False otherwise
    """
    if not is_own_profile:
        return True  # Not own profile, use other rules
    
    if user_role != Roles.VIEWER:
        return True  # Non-viewers can update their own profile
    
    # VIEWER restrictions for own profile
    restricted_fields = ["role", "account_type", "status", "active"]
    return field_name not in restricted_fields


def get_allowed_update_fields(is_own_profile: bool, user_role: str) -> list[str]:
    """
    Business rule: What fields can be updated?
    
    Args:
        is_own_profile: Is user updating their own profile?
        user_role: Role of the user
        
    Returns:
        List of allowed field names
    """
    basic_fields = [
        "first_name",
        "last_name",
        "gender",
        "email",
        "username",
    ]
    
    # VIEWERs cannot change these on own profile
    if is_own_profile and user_role == Roles.VIEWER:
        return basic_fields
    
    # Others can change additional fields
    return basic_fields + ["status", "active", "account_type", "role"]

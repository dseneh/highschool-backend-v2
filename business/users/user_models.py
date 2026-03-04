"""
User data models - Plain Python dataclasses (no Django)
"""
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime


@dataclass
class UserData:
    """Plain data object for user information"""
    id: str
    username: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    gender: Optional[str] = None
    id_number: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    account_type: Optional[str] = None
    school_id: Optional[str] = None
    is_staff: bool = False
    is_superuser: bool = False
    is_active: bool = True
    is_default_password: bool = False
    special_privileges: Optional[List[str]] = None
    last_login: Optional[datetime] = None
    photo: Optional[str] = None


@dataclass
class LoginCredentials:
    """Login request data"""
    identifier: str  # username, email, or id_number
    password: str


@dataclass
class LoginResult:
    """Login response data"""
    success: bool
    user: Optional[UserData] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    error: Optional[str] = None

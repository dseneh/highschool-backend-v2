"""
Users Business Logic Module

Framework-agnostic business logic for user management and authentication.
"""

from . import services
from . import adapters
from .user_models import UserData, LoginCredentials, LoginResult

__all__ = ['services', 'adapters', 'UserData', 'LoginCredentials', 'LoginResult']

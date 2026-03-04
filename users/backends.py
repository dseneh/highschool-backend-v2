"""
Custom authentication backends for multi-tenant user authentication
"""
from django.contrib.auth import get_user_model
from django.db.models import Q
from tenant_users.permissions.backend import UserBackend

User = get_user_model()


class MultiFieldAuthBackend(UserBackend):
    """
    Custom authentication backend that allows login with username, id_number, or email.
    
    Extends UserBackend from django-tenant-users to maintain tenant-specific
    permission checking while adding multi-field authentication support.
    
    Users can login with:
    - username + password
    - id_number + password
    - email + password
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user by username, id_number, or email.
        
        Args:
            request: The HTTP request object
            username: The identifier (can be username, id_number, or email)
            password: The password
            
        Returns:
            User instance if authenticated, None otherwise
        """
        if username is None:
            username = kwargs.get('username') or kwargs.get('id_number') or kwargs.get('email')
        
        if username is None or password is None:
            return None
        
        # Try to find user by username, id_number, or email
        user = None
        try:
            # Use Q object to search across all three fields
            f = Q(id_number=username) | Q(email=username) | Q(username=username)
            user = User.objects.get(f)
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            return None
        
        # If user found, check password and use parent class authentication
        if user and user.check_password(password):
            # Use parent class's user_can_authenticate to handle tenant-specific checks
            if super().user_can_authenticate(user):
                return user
        
        return None

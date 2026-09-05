"""Settings module for the API project."""

from .base import *

# SimpleJWT rotation/blacklisting only persists revoked refresh tokens when the
# blacklist app is installed. Keep its tables in the shared/public schema
# because global users and refresh endpoints are public-schema concerns.
_JWT_BLACKLIST_APP = "rest_framework_simplejwt.token_blacklist"
if _JWT_BLACKLIST_APP not in SHARED_APPS:
    SHARED_APPS.append(_JWT_BLACKLIST_APP)
if _JWT_BLACKLIST_APP not in INSTALLED_APPS:
    INSTALLED_APPS.append(_JWT_BLACKLIST_APP)

from .database import *
from .api import *
from .storage import *

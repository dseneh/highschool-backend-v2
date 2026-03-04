"""
REST Framework and API configuration
"""

from datetime import timedelta
from decouple import config

# REST Framework configuration
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "EXCEPTION_HANDLER": "api.exceptions.custom_exception_handler",
}

# JWT Settings
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("JWT_ACCESS_TOKEN_LIFETIME", default=60, cast=int)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("JWT_REFRESH_TOKEN_LIFETIME", default=7, cast=int)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": config("SECRET_KEY", default="django-insecure-change-me"),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
}

# CORS Settings
# Check if in debug mode
_DEBUG = config("DEBUG", default=True, cast=bool)

if _DEBUG:
    # In development: allow all localhost subdomains via regex
    CORS_ALLOWED_ORIGINS = config(
        "CORS_ALLOWED_ORIGINS",
        default="http://localhost:3000,http://127.0.0.1:3000",
        cast=lambda v: [s.strip() for s in v.split(",") if s.strip()],
    )
    # Regex patterns for subdomain-based origins (e.g., dujar.localhost:3000)
    # Using more permissive pattern for development
    CORS_ALLOWED_ORIGIN_REGEXES = [
        r"^https?://.*\.localhost:3000$",  # Matches any subdomain.localhost:3000 (more permissive)
        r"^https?://.*\.127\.0\.0\.1:3000$",  # Also match subdomain.127.0.0.1:3000
        r"^https?://localhost:3000$",  # Exact match for localhost
        r"^https?://127\.0\.0\.1:3000$",  # Exact match for 127.0.0.1
    ]
    # Uncomment for testing - allows all origins in development (NOT for production!)
    # CORS_ALLOW_ALL_ORIGINS = True
else:
    # Production: explicit origins only
    CORS_ALLOWED_ORIGINS = config(
        "CORS_ALLOWED_ORIGINS",
        default="",
        cast=lambda v: [s.strip() for s in v.split(",") if s.strip()],
    )
    CORS_ALLOWED_ORIGIN_REGEXES = config(
        "CORS_ALLOWED_ORIGIN_REGEXES",
        default="",
        cast=lambda v: [s.strip() for s in v.split(",") if s.strip()],
    )

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-tenant",  # Custom header for tenant identification
    "x-workspace",  # Alternative header for tenant identification
]

# Prod example
# CORS_ALLOWED_ORIGIN_REGEXES += [
#     r"^https?://([a-z0-9-]+)\.yourdomain\.com$",
#     r"^https?://yourdomain\.com$",
# ]
# APPEND_SLASH=False
if _DEBUG:
    CSRF_TRUSTED_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://*.localhost:3000",
    ]
else:
    CSRF_TRUSTED_ORIGINS = config(
        "CSRF_TRUSTED_ORIGINS",
        default="",
        cast=lambda v: [s.strip() for s in v.split(",") if s.strip()],
    )

# Swagger/OpenAPI Settings
SWAGGER_SETTINGS = {
    "SECURITY_DEFINITIONS": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
        }
    },
    "USE_SESSION_AUTH": False,
}

SECRET_AES_KEY = config("SECRET_AES_KEY", default="your-aes-secret-key-change-in-production")
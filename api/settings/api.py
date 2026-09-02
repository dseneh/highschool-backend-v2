"""REST Framework and API configuration."""

from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured
from decouple import config

_DEBUG = config("DEBUG", default=True, cast=bool)
_SECRET_KEY = config("SECRET_KEY", default="django-insecure-change-me" if _DEBUG else "")
if not _DEBUG and (not _SECRET_KEY or _SECRET_KEY.startswith("django-insecure-")):
    raise ImproperlyConfigured("SECRET_KEY must be explicitly configured in production.")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "api.authentication.TenantSessionAuthentication",
        "api.authentication.TenantAwareJWTAuthentication",
        "api.authentication.RBACSessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": config("API_THROTTLE_ANON", default="60/min"),
        "user": config("API_THROTTLE_USER", default="300/min"),
        "login": config("API_THROTTLE_LOGIN", default="5/min"),
        "password_reset": config("API_THROTTLE_PASSWORD_RESET", default="3/15min"),
        "activation": config("API_THROTTLE_ACTIVATION", default="3/15min"),
        "public_search": config("API_THROTTLE_PUBLIC_SEARCH", default="20/min"),
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": ["rest_framework.filters.SearchFilter", "rest_framework.filters.OrderingFilter"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "EXCEPTION_HANDLER": "api.exceptions.custom_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=config("JWT_ACCESS_TOKEN_LIFETIME", default=60, cast=int)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=config("JWT_REFRESH_TOKEN_LIFETIME", default=7, cast=int)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": _SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
}

if _DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="", cast=lambda v: [s.strip() for s in v.split(",") if s.strip()])
    CORS_ALLOWED_ORIGIN_REGEXES = config("CORS_ALLOWED_ORIGIN_REGEXES", default="", cast=lambda v: [s.strip() for s in v.split(",") if s.strip()])

CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ["content-type", "x-tenant"]
CORS_ALLOW_HEADERS = [
    "accept", "accept-encoding", "authorization", "content-type", "dnt", "origin", "user-agent",
    "x-csrftoken", "x-requested-with", "x-tenant", "x-workspace", "x-app-path", "x-app-platform",
    "x-app-version", "x-client-name", "x-device-name", "x-device-model", "x-device-brand", "x-device-type",
    "x-device-os", "x-device-os-version", "x-tenant-session",
]
CORS_ALLOW_METHODS = ["DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"]
CORS_PREFLIGHT_MAX_AGE = 86400

if _DEBUG:
    CSRF_TRUSTED_ORIGINS = [
        "http://localhost:3000", "http://127.0.0.1:3000", "http://*.localhost:3000",
        "http://*.lvh.me:3000", "http://lvh.me:3000", "http://*.localtest.me:3000",
        "http://localtest.me:3000", "http://localhost:8081", "http://127.0.0.1:8081",
    ]
else:
    CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=lambda v: [s.strip() for s in v.split(",") if s.strip()])

SECRET_AES_KEY = config("SECRET_AES_KEY", default="your-aes-secret-key-change-in-production" if _DEBUG else "")
if not _DEBUG and (not SECRET_AES_KEY or SECRET_AES_KEY == "your-aes-secret-key-change-in-production"):
    raise ImproperlyConfigured("SECRET_AES_KEY must be explicitly configured in production.")

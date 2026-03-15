"""
Base settings configuration
Contains core Django settings that are environment-agnostic

References:
- https://django-tenants.readthedocs.io/en/latest/install.html
- https://django-tenant-users.readthedocs.io/en/latest/pages/installation.html
"""

from pathlib import Path
from decouple import config

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Security
SECRET_KEY = config("SECRET_KEY", default="django-insecure-change-me-in-production")
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="", cast=lambda v: [s.strip() for s in v.split(",") if s.strip()])

if not ALLOWED_HOSTS:
    railway_public_domain = config("RAILWAY_PUBLIC_DOMAIN", default="").strip()
    if railway_public_domain:
        ALLOWED_HOSTS = [railway_public_domain]

# Always allow Railway's internal health check domain
if "healthcheck.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("healthcheck.railway.app")

# Allow local/internal hosts used by platform health probes and container runtime
for probe_host in ("localhost", "127.0.0.1", "[::1]"):
    if probe_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(probe_host)

# Allow Railway domains used by edge and service health probes
for railway_host in (".railway.app", ".up.railway.app"):
    if railway_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(railway_host)

# Application definition
# NOTE: django_tenants MUST be first in INSTALLED_APPS
SHARED_APPS = [
    "django_tenants",  # MUST be first - required by django-tenants
    # Django contrib apps (needed in public schema)
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "django.contrib.staticfiles",
    # django-tenant-users (global user management)
    # Reference: https://django-tenant-users.readthedocs.io/en/latest/pages/installation.html
    "tenant_users.permissions",
    "tenant_users.tenants",
    # Framework libraries (NO database models - code only)
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "storages",
    # Local shared apps (data in public schema OR abstract models/utilities)
    "common",  # Abstract base models (BaseModel, BasePersonModel) - no DB tables
    "users",  # User - lives in public schema (global users)
    "core",  # School model (TenantBase) - lives in public schema
]

TENANT_APPS = [
    # Django contrib apps (needed in tenant schemas for tenant-specific tables)
    "django.contrib.contenttypes",  # Tenant-specific content types
    "django.contrib.auth",  # Tenant-specific permissions (via django-tenant-users)
    "django.contrib.sessions",  # Tenant-specific sessions
    "django.contrib.messages",  # Tenant-specific messages
    "django.contrib.admin",  # Tenant-specific admin data
    "django.contrib.staticfiles",  # Tenant-specific static file references
    # django-tenant-users permissions (needed in tenant schemas)
    "tenant_users.permissions",
    # Local tenant apps (tenant-specific data)
    "academics",  # Academic models (AcademicYear, Semester, Division, GradeLevel, etc.)
    "students",  # Student models (Student, Enrollment, Attendance, GradeBook, etc.)
    "staff",  # Staff models (Department, Position, Staff, Teacher assignments, etc.)
    "grading",  # Grading models (GradeLetter, AssessmentType, GradeBook, Assessment, Grade, etc.)
    "finance",  # Finance models (BankAccount, Transaction, PaymentMethod, PaymentInstallment, etc.)
    "settings",  # Tenant-specific settings (grading settings)
    "reports",  # Reports (transaction reporting, exports, placeholders)
    "defaults",  # Default data creation for new tenants
]

# INSTALLED_APPS: Automatically constructed from SHARED_APPS and TENANT_APPS
# Reference: https://django-tenants.readthedocs.io/en/latest/install.html#configure-tenant-and-shared-applications
INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

# Tenant model configuration
TENANT_MODEL = "core.Tenant"  # Your Tenant model (TenantBase)
TENANT_DOMAIN_MODEL = "core.Domain"  # Domain model for routing

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # Must be before tenant middleware to handle OPTIONS requests
    "api.middleware.HeaderBasedTenantMiddleware",  # Handles schema switching via X-Tenant header (skips OPTIONS)
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "api.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "api.wsgi.application"

# Internationalization
LANGUAGE_CODE = config("LANGUAGE_CODE", default="en-us")
TIME_ZONE = config("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Custom user model
AUTH_USER_MODEL = "users.User"

# Authentication backend for django-tenant-users
# Reference: https://django-tenant-users.readthedocs.io/en/latest/pages/installation.html
AUTHENTICATION_BACKENDS = (
    "users.backends.MultiFieldAuthBackend",  # Multi-field authentication (id_number/username/email)
    "tenant_users.permissions.backend.UserBackend",  # Tenant-specific permissions
)

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 8,
        },
    },
]

# Static files

# Email configuration
# -------------------
# In development, set EMAIL_BACKEND to console to see emails in terminal.
# In production, either:
#   Option A (recommended): set RESEND_API_KEY to use Resend's REST API.
#   Option B: set EMAIL_HOST / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD for SMTP.
EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = config("EMAIL_HOST", default="smtp.resend.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@ezyschool.net")
EMAIL_FROM_NAME = config("EMAIL_FROM_NAME", default="EzySchool")

# Resend API key (takes priority over SMTP when set)
# Get yours at https://resend.com/
RESEND_API_KEY = config("RESEND_API_KEY", default="")

# Frontend integration
FRONTEND_DOMAIN = config("FRONTEND_DOMAIN", default="http://localhost:3000")
FRONTEND_USE_SUBDOMAIN = config("FRONTEND_USE_SUBDOMAIN", default=True, cast=bool)
FRONTEND_DEV_MODE = config("FRONTEND_DEV_MODE", default=True, cast=bool)
FRONTEND_PASSWORD_RESET_PATH = config("FRONTEND_PASSWORD_RESET_PATH", default="/reset-password")

# Branding for transactional emails
EMAIL_LOGO_URL = config("EMAIL_LOGO_URL", default="")

# How long (in seconds) a password-reset token stays valid (default: 1 hour)
PASSWORD_RESET_TIMEOUT = config("PASSWORD_RESET_TIMEOUT", default=3600, cast=int)

# Static files
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Media files
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Cache configuration
# Development: Uses LocMemCache (in-memory)
# Production: Uses Redis (set USE_REDIS=true and REDIS_URL)
# Format: redis://[:password]@host:port/db
USE_REDIS = config("USE_REDIS", default=False, cast=bool)
REDIS_URL = config("REDIS_URL", default="redis://127.0.0.1:6379/1")

if USE_REDIS and REDIS_URL.startswith("redis://"):
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": 300,  # Default cache timeout in seconds (5 minutes)
            "KEY_PREFIX": "ezyschool",  # Namespace all keys to prevent collisions
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "CONNECTION_POOL_KWARGS": {
                    "max_connections": 50,
                    "retry_on_timeout": True,
                },
                "SOCKET_CONNECT_TIMEOUT": 5,
                "SOCKET_TIMEOUT": 5,
                "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor",
            },
        }
    }
else:
    # Fallback to in-memory cache for development
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ezyschool-cache",
            "TIMEOUT": 300,
        }
    }

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True, cast=bool)
    SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=True, cast=bool)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = "DENY"
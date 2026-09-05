"""
Base settings configuration
Contains core Django settings that are environment-agnostic

References:
- https://django-tenants.readthedocs.io/en/latest/install.html
- https://django-tenant-users.readthedocs.io/en/latest/pages/installation.html
"""

from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from decouple import config

APP_ROOT_DOMAIN = config("APP_ROOT_DOMAIN", default="myezyschool.com").strip().lower()
LEGACY_APP_DOMAINS = config(
    "LEGACY_APP_DOMAINS",
    default="ezyschool.app,ezyschool.net",
    cast=lambda v: [s.strip().lower() for s in v.split(",") if s.strip()],
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Security: development may use a local fallback, production must provide a real secret.
DEBUG = config("DEBUG", default=True, cast=bool)
_INSECURE_SECRET_KEYS = {"", "django-insecure-change-me-in-production", "django-insecure-change-me"}
SECRET_KEY = config("SECRET_KEY", default="django-insecure-change-me-in-production" if DEBUG else "")
if not DEBUG and (SECRET_KEY in _INSECURE_SECRET_KEYS or SECRET_KEY.startswith("django-insecure-")):
    raise ImproperlyConfigured("SECRET_KEY must be explicitly configured with a strong production value.")

# Host-header validation. Wildcards are deliberately not used in production.
def _csv(value):
    return [item.strip() for item in value.split(",") if item.strip()]

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="", cast=_csv)
railway_public_domain = config("RAILWAY_PUBLIC_DOMAIN", default="").strip()
if railway_public_domain and railway_public_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(railway_public_domain)

if DEBUG:
    for local_host in ("localhost", "127.0.0.1", "[::1]", ".lvh.me", ".localtest.me"):
        if local_host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(local_host)
else:
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured("ALLOWED_HOSTS must be explicitly configured in production.")
    if "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured("ALLOWED_HOSTS cannot contain '*' in production.")

# Railway health probes use this fixed host. Add it explicitly rather than trusting all hosts.
if "healthcheck.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("healthcheck.railway.app")

SHARED_APPS = [
    "django_tenants",
    "django.contrib.contenttypes", "django.contrib.auth", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.admin", "django.contrib.staticfiles",
    "tenant_users.permissions", "tenant_users.tenants",
    "rest_framework", "rest_framework_simplejwt", "corsheaders", "storages",
    "auditlog", "common", "users", "core",
]

TENANT_APPS = [
    "django.contrib.contenttypes", "django.contrib.auth", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.admin", "django.contrib.staticfiles",
    "tenant_users.permissions", "auditlog", "academics", "students", "staff", "grading",
    "finance", "accounting", "hr", "payroll_v2", "employee_benefits",
    "employee_disbursements", "settings", "reports", "defaults", "notifications", "authorization",
]
INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

TENANT_MODEL = "core.Tenant"
TENANT_DOMAIN_MODEL = "core.Domain"

MIDDLEWARE = [
    "api.middleware.LegacyDomainRedirectMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "api.middleware.HeaderBasedTenantMiddleware",
    "api.middleware.ApiPerformanceMetricsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "common.audit_middleware.AuditlogDeviceMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "api.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug", "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "api.wsgi.application"

LANGUAGE_CODE = config("LANGUAGE_CODE", default="en-us")
TIME_ZONE = config("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.User"
AUTHENTICATION_BACKENDS = (
    "users.backends.MultiFieldAuthBackend",
    "tenant_users.permissions.backend.UserBackend",
)
AUTH_PASSWORD_VALIDATORS = [{
    "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    "OPTIONS": {"min_length": 8},
}]

EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
_local_smtp_configured = bool(EMAIL_HOST_USER and EMAIL_HOST_PASSWORD)
if DEBUG and _local_smtp_configured:
    email_backend_default = "django.core.mail.backends.smtp.EmailBackend"
elif DEBUG:
    email_backend_default = "django.core.mail.backends.console.EmailBackend"
else:
    email_backend_default = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_BACKEND = config("EMAIL_BACKEND", default=email_backend_default)
if not DEBUG and EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
_email_host_default = "smtp.gmail.com" if DEBUG and _local_smtp_configured else "smtp.resend.com"
EMAIL_HOST = config("EMAIL_HOST", default=_email_host_default)
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER if DEBUG and _local_smtp_configured else f"noreply@mail.{APP_ROOT_DOMAIN}")
EMAIL_FROM_NAME = config("EMAIL_FROM_NAME", default="EzySchool")
ADMIN_NOTIFICATION_EMAIL = config("ADMIN_NOTIFICATION_EMAIL", default=f"admin@{APP_ROOT_DOMAIN}")
SUPPORT_EMAIL = config("SUPPORT_EMAIL", default=f"support@{APP_ROOT_DOMAIN}")
RESEND_API_KEY = config("RESEND_API_KEY", default="")

FRONTEND_DOMAIN = config("FRONTEND_DOMAIN", default="http://localhost:3000")
FRONTEND_USE_SUBDOMAIN = config("FRONTEND_USE_SUBDOMAIN", default=True, cast=bool)
FRONTEND_DEV_MODE = config("FRONTEND_DEV_MODE", default=True, cast=bool)
FRONTEND_SUBDOMAIN_BASE = config("FRONTEND_SUBDOMAIN_BASE", default=APP_ROOT_DOMAIN)
FRONTEND_PASSWORD_RESET_PATH = config("FRONTEND_PASSWORD_RESET_PATH", default="/reset-password")
EMAIL_LOGO_URL = config("EMAIL_LOGO_URL", default="")
PASSWORD_RESET_TIMEOUT = config("PASSWORD_RESET_TIMEOUT", default=3600, cast=int)
PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS = config("PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS", default=60, cast=int)

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

USE_REDIS = config("USE_REDIS", default=False, cast=bool)
REDIS_URL = config("REDIS_URL", default="redis://127.0.0.1:6379/1")
if USE_REDIS and REDIS_URL.startswith("redis://"):
    CACHES = {"default": {
        "BACKEND": "django_redis.cache.RedisCache", "LOCATION": REDIS_URL, "TIMEOUT": 300,
        "KEY_PREFIX": "ezyschool",
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient", "CONNECTION_POOL_KWARGS": {"max_connections": 50, "retry_on_timeout": True}, "SOCKET_CONNECT_TIMEOUT": 5, "SOCKET_TIMEOUT": 5, "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor"},
    }}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "ezyschool-cache", "TIMEOUT": 300}}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True, cast=bool)
    SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=True, cast=bool)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

DELETE_PAID_LIVE_ROWS = config("DELETE_PAID_LIVE_ROWS", default=True, cast=bool)
API_PERF_METRICS_ENABLED = config("API_PERF_METRICS_ENABLED", default=False, cast=bool)
API_PERF_METRICS_PATH_PREFIXES = config(
    "API_PERF_METRICS_PATH_PREFIXES",
    default="/api/v1/students/,/api/v1/grading/,/api/v1/reports/,/api/v1/accounting/,/api/v1/finance/",
    cast=_csv,
)
API_PERF_METRICS_LOG_THRESHOLD_MS = config("API_PERF_METRICS_LOG_THRESHOLD_MS", default=400, cast=int)

"""
Database configuration for django-tenants
"""

from decouple import config
import dj_database_url

# Database configuration
DATABASE_URL = config("DATABASE_URL", default="")
DB_CONN_MAX_AGE = config("DB_CONN_MAX_AGE", default=30, cast=int)

if DATABASE_URL:
    parsed_db = dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=DB_CONN_MAX_AGE,
        ssl_require=config("DB_SSL_REQUIRE", default=False, cast=bool),
    )
    parsed_db["ENGINE"] = "django_tenants.postgresql_backend"
    DATABASES = {"default": parsed_db}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django_tenants.postgresql_backend",  # Required for django-tenants
            "NAME": config("DB_NAME", default="backend_v2_db"),
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
            "OPTIONS": {
                "sslmode": config("DB_SSL_MODE", default="prefer"),
            },
            "CONN_MAX_AGE": DB_CONN_MAX_AGE,
        }
    }

# Replaying every historical migration for every tenant created by a
# TenantTestCase is prohibitively expensive. Django's supported test setting
# disables migrations consistently for every installed app so syncdb can
# create interdependent tables (for example users.User.groups -> auth.Group)
# in dependency-safe model order. The CI migration-validation job leaves this
# flag disabled and exercises the complete migration history once.
if config("CI_FAST_TEST_SCHEMA", default=False, cast=bool):
    DATABASES["default"].setdefault("TEST", {})["MIGRATE"] = False
    TEST_RUNNER = "api.test_runner.CIFastTenantTestRunner"

# Database router for django-tenants
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

"""Multi-tenant storage configuration for local and S3-compatible object storage."""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ACCOUNTING_ATTACHMENT_MAX_FILE_SIZE_BYTES = config("ACCOUNTING_ATTACHMENT_MAX_FILE_SIZE_BYTES", default=10 * 1024 * 1024, cast=int)
ACCOUNTING_ATTACHMENT_ALLOWED_MIME_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif"]
ACCOUNTING_ATTACHMENT_ALLOWED_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif"]
ACCOUNTING_ATTACHMENT_UPLOAD_PREFIX = config("ACCOUNTING_ATTACHMENT_UPLOAD_PREFIX", default="accounting/attachments")

USE_S3_STORAGE = config("USE_S3_STORAGE", default=False, cast=bool)
PRIVATE_FILE_URL_EXPIRY_SECONDS = config("PRIVATE_FILE_URL_EXPIRY_SECONDS", default=300, cast=int)
TENANT_BACKUP_TIMEOUT_SECONDS = config("TENANT_BACKUP_TIMEOUT_SECONDS", default=1800, cast=int)
TENANT_BACKUP_STALE_MINUTES = config("TENANT_BACKUP_STALE_MINUTES", default=90, cast=int)
TENANT_BACKUP_SCHEDULE_ENABLED = config("TENANT_BACKUP_SCHEDULE_ENABLED", default=False, cast=bool)
TENANT_BACKUP_SCHEDULE_INTERVAL_HOURS = config("TENANT_BACKUP_SCHEDULE_INTERVAL_HOURS", default=168, cast=int)
TENANT_BACKUP_RETENTION_MANUAL_DAYS = config("TENANT_BACKUP_RETENTION_MANUAL_DAYS", default=30, cast=int)
TENANT_BACKUP_RETENTION_SCHEDULED_DAYS = config("TENANT_BACKUP_RETENTION_SCHEDULED_DAYS", default=30, cast=int)
TENANT_BACKUP_RETENTION_PRE_RESTORE_DAYS = config("TENANT_BACKUP_RETENTION_PRE_RESTORE_DAYS", default=90, cast=int)
TENANT_BACKUP_RETENTION_SYSTEM_DAYS = config("TENANT_BACKUP_RETENTION_SYSTEM_DAYS", default=30, cast=int)

if USE_S3_STORAGE:
    bucket_name = config("R2_BUCKET", default=config("AWS_STORAGE_BUCKET_NAME", default=""))
    access_key = config("R2_ACCESS_KEY_ID", default=config("AWS_ACCESS_KEY_ID", default=""))
    secret_key = config("R2_SECRET_ACCESS_KEY", default=config("AWS_SECRET_ACCESS_KEY", default=""))
    endpoint_url = config("R2_S3_ENDPOINT", default=config("AWS_S3_ENDPOINT_URL", default=None))
    region_name = config("AWS_S3_REGION_NAME", default="auto")

    missing = [name for name, value in {
        "R2_BUCKET/AWS_STORAGE_BUCKET_NAME": bucket_name,
        "R2_ACCESS_KEY_ID/AWS_ACCESS_KEY_ID": access_key,
        "R2_SECRET_ACCESS_KEY/AWS_SECRET_ACCESS_KEY": secret_key,
        "R2_S3_ENDPOINT/AWS_S3_ENDPOINT_URL": endpoint_url,
    }.items() if not value]
    if missing:
        raise ImproperlyConfigured(f"Object storage is enabled but required settings are missing: {', '.join(missing)}")

    backup_bucket = config("R2_BACKUP_BUCKET", default=bucket_name)
    backup_access_key = config("R2_BACKUP_ACCESS_KEY_ID", default=access_key)
    backup_secret_key = config("R2_BACKUP_SECRET_ACCESS_KEY", default=secret_key)
    backup_endpoint = config("R2_BACKUP_S3_ENDPOINT", default=endpoint_url)

    STORAGES = {
        "default": {"BACKEND": "core.storage.TenantAwareS3Storage", "OPTIONS": {"bucket_name": bucket_name, "access_key": access_key, "secret_key": secret_key, "endpoint_url": endpoint_url, "region_name": region_name, "file_overwrite": False, "default_acl": None, "querystring_auth": True, "querystring_expire": PRIVATE_FILE_URL_EXPIRY_SECONDS}},
        "backups": {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": {"bucket_name": backup_bucket, "access_key": backup_access_key, "secret_key": backup_secret_key, "endpoint_url": backup_endpoint, "region_name": region_name, "file_overwrite": False, "default_acl": None, "querystring_auth": True, "querystring_expire": PRIVATE_FILE_URL_EXPIRY_SECONDS}},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

    AWS_STORAGE_BUCKET_NAME = bucket_name
    AWS_ACCESS_KEY_ID = access_key
    AWS_SECRET_ACCESS_KEY = secret_key
    AWS_S3_ENDPOINT_URL = endpoint_url
    AWS_S3_REGION_NAME = region_name
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = True
    AWS_QUERYSTRING_EXPIRE = PRIVATE_FILE_URL_EXPIRY_SECONDS
else:
    STORAGES = {
        "default": {"BACKEND": "django_tenants.files.storage.TenantFileSystemStorage"},
        "backups": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": str(BASE_DIR / "backups-data")}},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
